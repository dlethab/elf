<?php
declare(strict_types=1);

namespace Elf;

use Elf\Http\HttpException;
use Elf\Http\Redirect;
use Elf\Http\Request;
use Elf\Http\Response;
use Elf\Http\Router;
use Elf\Http\Session;
use Elf\Services\Accounts;
use Elf\Services\CurrentUser;
use Twig\Environment;

/**
 * The application: configuration, routes, and one request at a time (the Python edition's create_app()).
 * Pages are rendered with Twig from templates/; the routes are registered by the classes in src/Web.
 */
final class App
{
    public static ?App $current = null;
    public array $config;
    public Router $router;
    public Environment $twig;
    public Session $session;
    public ?Request $req = null;
    public ?CurrentUser $user = null;
    /** Per-request values (Flask's g): e.g. "embed" for the framed map. */
    public array $g = [];
    private ?Db $db = null;
    private array $flashesShown = [];

    public function __construct(array $overrides = [], ?array $envFile = null)
    {
        $this->config = Config::load($overrides, $envFile);
        $this->config['CSP'] = Security::buildCsp($this->config);
        $path = $this->config['DATABASE_PATH'];
        $shared = $this->config['_SHARED_CONNECTION'] ?? null;
        if ($path !== ':memory:' && !$shared) {
            $full = Config::path($path);
            if (!is_dir(dirname($full))) {
                mkdir(dirname($full), 0770, true);
            }
            if ($this->config['AUTO_MIGRATE']) {
                (new Db($full))->migrate();
            } elseif (is_file($full)) {
                $pending = Db::pendingMigrations($full);
                if ($pending) {          // pages that need the new tables would fail: say so where an administrator looks
                    error_log('[elf] The database needs ' . count($pending) . ' update(s) (' . implode(', ', $pending)
                        . '). Back it up, then run: php bin/elf migrate');
                }
            }
        }
        $this->session = new Session((string) $this->config['SECRET_KEY']);
        $this->router = new Router();
        $this->twig = View::environment($this);
        Web\PublicController::routes($this);
        Web\AuthController::routes($this);
        Web\DashboardController::routes($this);
        Web\EditorController::routes($this);
        Web\AdminController::routes($this);
        Web\CommunityController::routes($this);
        if (in_array($this->config['ENV'], ['development', 'testing'], true)) {
            Web\AuthController::devRoutes($this);     // never registered in production
        }
    }

    public function db(): Db
    {
        if ($this->config['_SHARED_CONNECTION'] ?? null) {
            return $this->config['_SHARED_CONNECTION'];     // tests use one in-memory database
        }
        return $this->db ??= new Db(Config::path($this->config['DATABASE_PATH']));
    }

    public function url(string $name, array $params = []): string
    {
        if ($name === 'static') {
            return $this->staticUrl((string) ($params['filename'] ?? ''));
        }
        return $this->router->url($name, $params);
    }

    /**
     * /static/<file>?v=<modification time>, so files can be cached for a year and a deployment that changes a file
     * changes its address. Folders (the terrain tile root) are left as they are.
     */
    public function staticUrl(string $filename): string
    {
        $f = Config::root() . '/public/static/' . $filename;
        $url = '/static/' . $filename;
        return is_file($f) ? $url . '?v=' . dechex((int) filemtime($f)) : $url;
    }

    public function flash(string $message, string $category = 'message'): void
    {
        $f = $this->session->get('_flashes', []);
        $f[] = [$category, $message];
        $this->session->set('_flashes', $f);
    }

    /** get_flashed_messages(with_categories=true): read once, then gone. */
    public function takeFlashes(): array
    {
        if ($this->session->has('_flashes')) {
            $this->flashesShown = array_merge($this->flashesShown, $this->session->pop('_flashes', []));
        }
        return $this->flashesShown;
    }

    public function render(string $template, array $context = [], int $status = 200): Response
    {
        return new Response($this->twig->render($template, View::context($this, $context)), $status);
    }

    public function ip(): string
    {
        return $this->req?->remoteAddr ?: '?';
    }

    public function handle(Request $req): Response
    {
        self::$current = $this;
        $this->req = $req;
        $this->user = null;
        $this->g = [];
        $this->flashesShown = [];
        I18n::$current = (isset(I18n::LANGUAGES[$req->cookies[I18n::COOKIE] ?? '']) ? $req->cookies[I18n::COOKIE] : I18n::DEFAULT);
        $this->session->load($req->cookies[Session::COOKIE] ?? null);
        $this->session->modified = false;
        try {
            if (str_starts_with($req->path, '/static/')) {
                $resp = Web\StaticFiles::serve($this, $req);
            } else {
                $resp = $this->dispatch($req);
            }
        } catch (\Throwable $e) {
            $resp = $this->errorResponse($e);
        }
        Security::applyHeaders($this, $req, $resp);
        if ($this->session->modified) {
            $value = $this->session->serialize((int) $this->config['SESSION_LIFETIME_SECONDS']);
            $secure = $this->config['ENV'] === 'production';
            if ($value === '') {
                $resp->setCookie(Session::COOKIE, '', 0, '/', true, $secure, 'Lax', 0);
            } else {
                $resp->setCookie(Session::COOKIE, $value, $this->session->permanent ? (int) $this->config['SESSION_LIFETIME_SECONDS'] : 0, '/', true, $secure);
            }
        }
        if ($req->method === 'HEAD') {
            $resp->body = '';
        }
        return $resp;
    }

    private function dispatch(Request $req): Response
    {
        $m = $this->router->match($req->method, $req->path);
        if (is_array($m)) {
            $req->endpoint = $m[0]['name'];
            $req->viewArgs = $m[1];
        }
        // as Flask: the visitor is known (and the form checked) before "not found", so error pages show their menu
        $raw = $this->session->get('sid');
        if ($raw) {
            $this->user = Accounts::loadSession($this->db(), $raw);
            if ($this->user === null) {
                $this->session->pop('sid');
            }
        }
        $max = (int) ($this->config['MAX_CONTENT_LENGTH'] ?? 0);
        // PHP itself drops a body larger than post_max_size (the form would then look like an expired session)
        $phpMax = self::iniBytes((string) ini_get('post_max_size'));
        if (($max && $req->contentLength > $max) || ($phpMax > 0 && $req->contentLength > $phpMax)) {
            throw new HttpException(413);
        }
        Security::checkCsrf($this, $req);
        if ($m === 405) {
            throw new HttpException(405);
        }
        if ($m === null) {
            throw new HttpException(404);
        }
        [$route, $params] = $m;
        $out = ($route['handler'])($params);
        if (is_string($out)) {
            return new Response($out);
        }
        return $out;
    }

    private const ERRORS = [
        400 => ['Request could not be processed', 'Please go back and try again.'],
        403 => ['Not permitted', 'You do not have permission to do this.'],
        404 => ['Not found', 'This page does not exist or is not publicly available.'],
        405 => ['Method not allowed', 'That action is not available here.'],
        413 => ['Too large', 'The submitted content is too large.'],
        429 => ['Too many requests', 'Please wait a little and try again.'],
    ];

    private function errorResponse(\Throwable $e): Response
    {
        if ($e instanceof Redirect) {
            return Response::redirect($e->location);
        }
        if ($e instanceof HttpException && isset(self::ERRORS[$e->status])) {
            [$title, $text] = self::ERRORS[$e->status];
            $text = ($e->status === 400 && $e->description) ? $e->description : $text;
            try {
                return $this->render('errors/error.html', ['code' => $e->status, 'title' => $title, 'text' => $text], $e->status);
            } catch (\Throwable $inner) {
                return new Response(htmlspecialchars($title), $e->status);
            }
        }
        // details go to the server log only
        error_log('[elf] Unhandled error: ' . get_class($e) . ': ' . $e->getMessage() . ' at ' . $e->getFile() . ':' . $e->getLine()
            . "\n" . $e->getTraceAsString());
        try {
            return $this->render('errors/error.html', ['code' => 500, 'title' => 'Something went wrong',
                'text' => 'The error has been logged. Please try again later.'], 500);
        } catch (\Throwable) {
            return new Response('Something went wrong', 500);
        }
    }

    /** A php.ini size ("8M", "1G", "-1") in bytes; -1 or 0 means no limit. */
    public static function iniBytes(string $v): int
    {
        $v = trim($v);
        $n = (int) $v;
        return match (strtolower(substr($v, -1))) {
            'g' => $n * 1024 ** 3, 'm' => $n * 1024 ** 2, 'k' => $n * 1024, default => $n,
        };
    }

    public function pageUrl(int $n): string
    {
        $args = $this->req?->query ?? [];
        $args['page'] = $n;
        return $this->req->path . '?' . http_build_query($args, '', '&', PHP_QUERY_RFC1738);
    }

    public function unreadNotifications(): int
    {
        if (!$this->user) {
            return 0;
        }
        return (int) $this->db()->val('SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL', [$this->user->id]);
    }
}
