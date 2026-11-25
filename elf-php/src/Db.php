<?php
declare(strict_types=1);

namespace Elf;

use PDO;
use PDOStatement;

/**
 * SQLite access, explicit transactions, and the migration runner. The schema is the Python edition's, migration
 * for migration, so the two editions can open the same database file.
 */
final class Db
{
    public const DATE_MACRO = '{p}_start TEXT, {p}_end TEXT, '
        . "{p}_precision TEXT NOT NULL DEFAULT 'unknown' CHECK ({p}_precision IN ({prec}) "
        . "AND ({p}_precision <> 'unknown' OR {p}_start IS NULL)), "
        . '{p}_note TEXT';
    public const FK_OFF_MARKER = '-- migrate: foreign_keys=off';

    public PDO $pdo;
    private int $depth = 0;
    private int $savepoints = 0;

    public function __construct(public readonly string $path)
    {
        $dsn = $path === ':memory:' ? 'sqlite::memory:' : 'sqlite:' . $path;
        $this->pdo = new PDO($dsn, null, null, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_TIMEOUT => 10,
        ]);
        $this->pdo->exec('PRAGMA foreign_keys = ON');
        if ($path !== ':memory:') {
            $this->pdo->exec('PRAGMA journal_mode = WAL');
        }
    }

    public static function migrationsDir(): string
    {
        return Config::root() . '/migrations';
    }

    public function q(string $sql, array $params = []): PDOStatement
    {
        $st = $this->pdo->prepare($sql);
        $i = 0;
        foreach ($params as $k => $v) {
            $key = is_int($k) ? ++$i : (str_starts_with($k, ':') ? $k : ':' . $k);
            $type = match (true) {
                is_int($v) => PDO::PARAM_INT,
                is_bool($v) => PDO::PARAM_INT,
                $v === null => PDO::PARAM_NULL,
                default => PDO::PARAM_STR,
            };
            $st->bindValue($key, is_bool($v) ? (int) $v : $v, $type);
        }
        $st->execute();
        return $st;
    }

    public function one(string $sql, array $params = []): ?array
    {
        $r = $this->q($sql, $params)->fetch(PDO::FETCH_ASSOC);
        return $r === false ? null : $r;
    }

    public function all(string $sql, array $params = []): array
    {
        return $this->q($sql, $params)->fetchAll(PDO::FETCH_ASSOC);
    }

    /** The first column of every row. */
    public function col(string $sql, array $params = []): array
    {
        return $this->q($sql, $params)->fetchAll(PDO::FETCH_COLUMN, 0);
    }

    public function val(string $sql, array $params = []): mixed
    {
        $v = $this->q($sql, $params)->fetchColumn();
        return $v === false ? null : $v;
    }

    public function exec(string $sql, array $params = []): int
    {
        return $this->q($sql, $params)->rowCount();
    }

    public function insert(string $sql, array $params = []): int
    {
        $this->q($sql, $params);
        return (int) $this->pdo->lastInsertId();
    }

    public function inTransaction(): bool
    {
        return $this->depth > 0;
    }

    /** Atomic block. Nested use becomes a savepoint, so services can compose safely. */
    public function tx(callable $fn): mixed
    {
        if ($this->depth > 0) {
            $name = 'sp_' . (++$this->savepoints);
            $this->pdo->exec("SAVEPOINT {$name}");
            $this->depth++;
            try {
                $out = $fn($this);
            } catch (\Throwable $e) {
                $this->depth--;
                $this->pdo->exec("ROLLBACK TO {$name}");
                $this->pdo->exec("RELEASE {$name}");
                throw $e;
            }
            $this->depth--;
            $this->pdo->exec("RELEASE {$name}");
            return $out;
        }
        $this->pdo->exec('BEGIN IMMEDIATE');
        $this->depth = 1;
        try {
            $out = $fn($this);
        } catch (\Throwable $e) {
            $this->depth = 0;
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
        $this->depth = 0;
        $this->pdo->exec('COMMIT');
        return $out;
    }

    public static function expand(string $sql): string
    {
        $sql = preg_replace_callback('/\{\{VOCAB:(\w+)\}\}/', fn ($m) => implode(',', array_map(fn ($v) => "'{$v}'", Vocab::macro($m[1]))), $sql);
        $prec = implode(',', array_map(fn ($v) => "'{$v}'", Vocab::PRECISIONS));
        return preg_replace_callback('/\{\{DATE:(\w+)\}\}/', fn ($m) => str_replace(['{p}', '{prec}'], [$m[1], $prec], self::DATE_MACRO), $sql);
    }

    /** @return string[] migration names, in order */
    public static function migrationFiles(): array
    {
        $files = glob(self::migrationsDir() . '/*.sql') ?: [];
        sort($files, SORT_STRING);
        return $files;
    }

    /** Names of migrations not yet applied to the database file (read-only check). */
    public static function pendingMigrations(string $path): array
    {
        $done = [];
        try {
            $pdo = new PDO('sqlite:' . $path, null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
            $done = array_flip($pdo->query('SELECT version FROM schema_migrations')->fetchAll(PDO::FETCH_COLUMN, 0));
        } catch (\PDOException) {
            $done = [];
        }
        $out = [];
        foreach (self::migrationFiles() as $f) {
            $stem = basename($f, '.sql');
            if (!isset($done[$stem])) {
                $out[] = $stem;
            }
        }
        return $out;
    }

    /**
     * Apply pending migrations in order. Each file runs atomically.
     *
     * A migration that rebuilds a table (SQLite cannot change a CHECK constraint in place) starts with the line
     * `-- migrate: foreign_keys=off`. It then runs with foreign-key enforcement suspended, as SQLite's documented
     * table-rebuild procedure requires, and is committed only if `PRAGMA foreign_key_check` finds no broken reference.
     */
    public function migrate(): array
    {
        $this->pdo->exec("CREATE TABLE IF NOT EXISTS schema_migrations ("
            . "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')))");
        $done = array_flip($this->col('SELECT version FROM schema_migrations'));
        $applied = [];
        foreach (self::migrationFiles() as $f) {
            $stem = basename($f, '.sql');
            if (isset($done[$stem])) {
                continue;
            }
            $sql = self::expand((string) file_get_contents($f));
            $record = "\nINSERT INTO schema_migrations(version) VALUES ('{$stem}');";
            $fkOff = str_starts_with(ltrim($sql), self::FK_OFF_MARKER);
            try {
                if ($fkOff) {
                    $this->pdo->exec('PRAGMA foreign_keys = OFF');
                    $this->pdo->exec("BEGIN;\n" . $sql . $record);
                    $broken = $this->all('PRAGMA foreign_key_check');
                    if ($broken) {
                        throw new \RuntimeException("Migration {$stem} would break " . count($broken) . ' references; rolled back.');
                    }
                    $this->pdo->exec('COMMIT');
                } else {
                    $this->pdo->exec("BEGIN;\n" . $sql . $record . "\nCOMMIT;");
                }
            } catch (\Throwable $e) {
                try {
                    $this->pdo->exec('ROLLBACK');
                } catch (\Throwable) {
                }
                throw $e;
            } finally {
                if ($fkOff) {
                    $this->pdo->exec('PRAGMA foreign_keys = ON');
                }
            }
            $applied[] = $stem;
        }
        return $applied;
    }
}
