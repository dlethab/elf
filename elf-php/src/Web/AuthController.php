<?php
declare(strict_types=1);

namespace Elf\Web;

use Elf\App;
use Elf\Http\Response;
use Elf\Security;
use Elf\Services\AccountError;
use Elf\Services\Accounts;
use Elf\Services\Mfa;
use Elf\Services\RateLimit;

/** Registration, sign-in (with optional two-step), sign-out, email verification, password reset. All state changes are POST + CSRF. */
final class AuthController extends Controller
{
    public static function routes(App $app): void
    {
        $c = new self($app);
        $c->route('GET|POST', '/auth/register', 'register', 'auth.register');
        $c->route('GET|POST', '/auth/login', 'login', 'auth.login');
        $c->route('GET|POST', '/auth/two-step', 'twoStep', 'auth.two_step');
        $c->route('POST', '/auth/logout', 'logout', 'auth.logout');
        $c->route('GET', '/auth/verify/<token>', 'verify', 'auth.verify');
        $c->route('POST', '/auth/resend-verification', 'resendVerification', 'auth.resend_verification');
        $c->route('GET|POST', '/auth/forgot', 'forgot', 'auth.forgot');
        $c->route('GET|POST', '/auth/reset/<token>', 'reset', 'auth.reset');
    }

    /** Development helper: read queued email without an SMTP provider. Never registered in production. */
    public static function devRoutes(App $app): void
    {
        $c = new self($app);
        $c->route('GET', '/dev/outbox', 'outbox', 'dev.outbox');
    }

    /** Fresh session on every sign-in (prevents session fixation). */
    public static function startSession(App $app, int $userId): void
    {
        $raw = Accounts::createSession($app->db(), $userId, $app->ip(), $app->req->header('User-Agent'),
            (int) $app->config['SESSION_LIFETIME_SECONDS']);
        $app->session->clear();
        $app->session->permanent = true;
        $app->session->set('sid', $raw);
    }

    public function register(): Response
    {
        if ($this->viewer()) {
            return $this->redirect($this->url('dashboard.home'));
        }
        $errors = [];
        $values = ['email' => '', 'username' => '', 'display_name' => ''];
        if ($this->isPost()) {
            foreach ($values as $k => $_) {
                $values[$k] = (string) $this->req()->post($k, '');
            }
            if ($this->req()->post('website')) {                  // honeypot
                $this->abort(400);
            }
            if ($this->req()->post('password') !== $this->req()->post('password2')) {
                $errors['password2'] = 'The passwords do not match.';
            } else {
                $db = $this->db();
                try {
                    $uid = $db->tx(fn () => Accounts::register($db, $values['email'], $values['username'], $values['display_name'],
                        (string) $this->req()->post('password', ''), $this->ip(), $this->app->config['BASE_URL']));
                    self::startSession($this->app, $uid);
                    $this->flash('Your account has been created. Check your email for a link to verify your address; you can browse and save drafts meanwhile.', 'ok');
                    return $this->redirect($this->url('dashboard.home'));
                } catch (AccountError $e) {
                    $errors = $e->errors;
                }
            }
        }
        return $this->render('auth/register.html', ['errors' => $errors, 'values' => $values], $errors ? 400 : 200);
    }

    public function login(): Response
    {
        $nxt = Security::safeNext($this->req()->value('next'), $this->url('dashboard.home'));
        if ($this->viewer()) {
            return $this->redirect($nxt);
        }
        $errors = [];
        $identifier = '';
        if ($this->isPost()) {
            $identifier = (string) $this->req()->post('identifier', '');
            $db = $this->db();
            $result = $db->tx(fn () => Accounts::authenticate($db, $identifier, (string) $this->req()->post('password', ''), $this->ip()));
            if ($result === 'locked') {
                $errors['form'] = 'Too many failed attempts. Please wait 15 minutes, or reset your password.';
            } elseif ($result === null) {
                $errors['form'] = 'That email or username and password do not match an active account.';
            } else {
                if ($db->val('SELECT totp_enabled_at FROM users WHERE id=?', [$result])) {
                    // password correct; the session is created only after the second step
                    $this->app->session->clear();
                    $this->app->session->set('mfa_pending', ['uid' => $result, 'exp' => time() + 300, 'next' => $nxt]);
                    return $this->redirect($this->url('auth.two_step'));
                }
                $db->tx(fn () => self::startSession($this->app, (int) $result));
                return $this->redirect($nxt);
            }
        }
        return $this->render('auth/login.html', ['errors' => $errors, 'identifier' => $identifier, 'next' => $nxt], $errors ? 400 : 200);
    }

    public function twoStep(): Response
    {
        $pending = $this->app->session->get('mfa_pending');
        if (!is_array($pending) || ($pending['exp'] ?? 0) < time()) {
            $this->app->session->pop('mfa_pending');
            $this->flash('Please sign in again.', 'error');
            return $this->redirect($this->url('auth.login'));
        }
        $error = null;
        if ($this->isPost()) {
            $db = $this->db();
            $ok = $db->tx(fn () => Mfa::verify($db, (int) $pending['uid'], $this->req()->post('code'), $this->ip()));
            if ($ok === true) {
                $db->tx(fn () => self::startSession($this->app, (int) $pending['uid']));
                return $this->redirect(Security::safeNext($pending['next'] ?? null, $this->url('dashboard.home')));
            }
            $error = $ok === 'locked' ? 'Too many failed attempts. Please wait 15 minutes, or reset your password.'
                : 'That code is not valid. Enter the current code from your app, or one of your recovery codes.';
        }
        return $this->render('auth/two_step.html', ['error' => $error], $error ? 400 : 200);
    }

    public function logout(): Response
    {
        $raw = $this->app->session->get('sid');
        if ($raw) {
            $db = $this->db();
            $db->tx(fn () => Accounts::revokeSession($db, $raw));
        }
        $this->app->session->clear();
        $this->flash('You have signed out.', 'ok');
        return $this->redirect($this->url('public.home'));
    }

    public function verify(string $token): Response
    {
        $db = $this->db();
        $ok = $db->tx(fn () => Accounts::verifyEmail($db, $token));
        if ($ok) {
            $this->flash('Your email address is verified. You can now submit contributions for review.', 'ok');
        } else {
            $this->flash('That verification link is invalid, already used, or expired. You can request a new one from your dashboard.', 'error');
        }
        return $this->redirect($this->viewer() ? $this->url('dashboard.home') : $this->url('auth.login'));
    }

    public function resendVerification(): Response
    {
        $this->loginRequired();
        $db = $this->db();
        $u = $this->me();
        $db->tx(function () use ($db, $u) {
            if ($u->email_verified) {
                $this->flash('Your email address is already verified.', 'ok');
            } elseif (RateLimit::allow($db, "verify:{$u->id}", 3, 3600)) {
                Accounts::sendVerification($db, $u->id, $u->email, $this->app->config['BASE_URL']);
                $this->flash('A new verification link has been sent.', 'ok');
            } else {
                $this->flash('Please wait before requesting another link.', 'error');
            }
        });
        return $this->redirect($this->url('dashboard.home'));
    }

    public function forgot(): Response
    {
        if ($this->isPost()) {
            $db = $this->db();
            $db->tx(fn () => Accounts::requestReset($db, (string) $this->req()->post('email', ''), $this->ip(), $this->app->config['BASE_URL']));
            // Identical response whether or not the address exists (no account enumeration).
            $this->flash('If an account uses that address, a password-reset link has been sent to it.', 'ok');
            return $this->redirect($this->url('auth.login'));
        }
        return $this->render('auth/forgot.html');
    }

    public function reset(string $token): Response
    {
        $db = $this->db();
        $errors = [];
        if ($this->isPost()) {
            if ($this->req()->post('password') !== $this->req()->post('password2')) {
                $errors['password2'] = 'The passwords do not match.';
            } else {
                try {
                    $db->tx(fn () => Accounts::resetPassword($db, $token, (string) $this->req()->post('password', '')));
                    $this->app->session->clear();
                    $this->flash('Your password has been changed and all other sessions were signed out. Please sign in.', 'ok');
                    return $this->redirect($this->url('auth.login'));
                } catch (AccountError $e) {
                    $errors = $e->errors;
                }
            }
        } elseif (!Accounts::resetTokenValid($db, $token)) {
            $errors['form'] = 'This reset link is invalid or has expired.';
        }
        return $this->render('auth/reset.html', ['errors' => $errors, 'token' => $token], $errors ? 400 : 200);
    }

    public function outbox(): Response
    {
        return $this->render('auth/dev_outbox.html', ['rows' => $this->db()->all('SELECT * FROM outbox ORDER BY id DESC LIMIT 50')]);
    }
}
