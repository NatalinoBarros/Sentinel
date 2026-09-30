<?php

/**
 * Cliente PHP sem dependencias externas para o Automation Sentinel.
 *
 * Uso:
 *
 * sentinel_monitor('meu_job', 'Meu Job', function () {
 *     // rotina monitorada
 * });
 */

if (!defined('SENTINEL_DEFAULT_SERVER_URL')) {
    define('SENTINEL_DEFAULT_SERVER_URL', 'http://127.0.0.1:8050');
}

if (!class_exists('SentinelMonitor', false)) {
    final class SentinelMonitor
    {
        private $jobId;
        private $name;
        private $serverUrl;
        private $timeout;
        private $executionId;
        private $startedAt;
        private $finished = false;
        private $shutdownHandler;

        public function __construct($jobId, $name = null, $serverUrl = null, $timeout = 5.0)
        {
            $jobId = trim((string) $jobId);
            if ($jobId === '') {
                throw new InvalidArgumentException('O job_id do Sentinel nao pode ser vazio.');
            }

            if ($serverUrl === null || trim((string) $serverUrl) === '') {
                $serverUrl = getenv('SENTINEL_SERVER_URL');
            }

            $this->jobId = $jobId;
            $this->name = ($name === null || trim((string) $name) === '') ? $jobId : (string) $name;
            $this->serverUrl = rtrim($serverUrl ?: SENTINEL_DEFAULT_SERVER_URL, '/');
            $this->timeout = max(0.1, (float) $timeout);
        }

        /**
         * Executa uma rotina e preserva seu valor de retorno ou sua excecao original.
         */
        public function run(callable $callback)
        {
            $this->start();

            try {
                $result = call_user_func($callback);
                $this->success();
                return $result;
            } catch (Throwable $error) {
                $this->failure($error->getMessage() ?: get_class($error), (string) $error);
                throw $error;
            }
        }

        private function start()
        {
            $this->startedAt = microtime(true);

            // O handler precisa existir antes do primeiro acesso HTTP para tambem
            // proteger a fase de inicializacao do monitor.
            $monitor = $this;
            $this->shutdownHandler = function () use ($monitor) {
                $monitor->handleShutdown();
            };
            register_shutdown_function($this->shutdownHandler);

            $response = $this->post('/api/ping/' . rawurlencode($this->jobId) . '/start', array(
                'job_name' => $this->name,
                'language' => 'php',
            ));

            if (is_array($response) && isset($response['execution_id'])) {
                $this->executionId = $response['execution_id'];
            }
        }

        private function success()
        {
            $this->finished = true;
            $this->post('/api/ping/' . rawurlencode($this->jobId) . '/success', array(
                'execution_id' => $this->executionId,
                'duration_seconds' => $this->duration(),
            ));
        }

        private function failure($message, $traceback = null)
        {
            if ($this->finished) {
                return;
            }

            $this->finished = true;
            $this->post('/api/ping/' . rawurlencode($this->jobId) . '/fail', array(
                'error_message' => (string) $message,
                'traceback' => $traceback,
                'execution_id' => $this->executionId,
                'duration_seconds' => $this->duration(),
            ));
        }

        public function handleShutdown()
        {
            if ($this->finished) {
                return;
            }

            $lastError = error_get_last();
            $fatalTypes = array(E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR, E_USER_ERROR);

            if ($lastError && in_array($lastError['type'], $fatalTypes, true)) {
                $message = isset($lastError['message']) ? $lastError['message'] : 'Erro fatal no PHP';
                $traceback = sprintf(
                    "%s em %s:%s",
                    $message,
                    isset($lastError['file']) ? $lastError['file'] : 'arquivo desconhecido',
                    isset($lastError['line']) ? $lastError['line'] : '?'
                );
                $this->failure($message, $traceback);
                return;
            }

            $this->failure(
                'A rotina PHP foi encerrada com exit/die antes de concluir.',
                'O callback monitorado terminou durante o shutdown sem retornar ao SentinelMonitor.'
            );
        }

        private function duration()
        {
            return max(0.0, microtime(true) - $this->startedAt);
        }

        /**
         * Envia JSON por cURL quando disponivel, com fallback para streams do PHP.
         * Falhas no Sentinel nunca interrompem a automacao monitorada (fail-open).
         */
        private function post($path, array $payload)
        {
            $url = $this->serverUrl . $path;
            $json = json_encode($payload);
            if ($json === false) {
                $this->warn('Nao foi possivel serializar o payload JSON.');
                return null;
            }

            if (function_exists('curl_init')) {
                return $this->postWithCurl($url, $json);
            }

            return $this->postWithStream($url, $json);
        }

        private function postWithCurl($url, $json)
        {
            $curl = curl_init($url);
            curl_setopt_array($curl, array(
                CURLOPT_POST => true,
                CURLOPT_POSTFIELDS => $json,
                CURLOPT_HTTPHEADER => array(
                    'Content-Type: application/json',
                    'User-Agent: Sentinel-PHP-Client/1.0',
                ),
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_CONNECTTIMEOUT => (int) ceil($this->timeout),
                CURLOPT_TIMEOUT_MS => (int) ceil($this->timeout * 1000),
            ));

            $body = curl_exec($curl);
            $error = curl_error($curl);
            $status = (int) curl_getinfo($curl, CURLINFO_HTTP_CODE);
            curl_close($curl);

            if ($body === false || $status < 200 || $status >= 300) {
                $detail = $error ?: ('HTTP ' . $status);
                $this->warn('Nao foi possivel contatar ' . $url . ': ' . $detail);
                return null;
            }

            return $this->decodeResponse($body);
        }

        private function postWithStream($url, $json)
        {
            $context = stream_context_create(array(
                'http' => array(
                    'method' => 'POST',
                    'header' => "Content-Type: application/json\r\nUser-Agent: Sentinel-PHP-Client/1.0\r\n",
                    'content' => $json,
                    'timeout' => $this->timeout,
                    'ignore_errors' => true,
                ),
            ));

            $body = @file_get_contents($url, false, $context);
            $headers = isset($http_response_header) ? $http_response_header : array();
            $status = 0;
            if (isset($headers[0]) && preg_match('/\s(\d{3})\s/', $headers[0], $matches)) {
                $status = (int) $matches[1];
            }

            if ($body === false || $status < 200 || $status >= 300) {
                $this->warn('Nao foi possivel contatar ' . $url . ': HTTP ' . $status);
                return null;
            }

            return $this->decodeResponse($body);
        }

        private function decodeResponse($body)
        {
            $decoded = json_decode($body, true);
            return is_array($decoded) ? $decoded : null;
        }

        private function warn($message)
        {
            error_log('[Sentinel Monitor Warning] ' . $message);
        }
    }
}

if (!function_exists('sentinel_monitor')) {
    /**
     * Atalho semelhante a um decorator para envolver uma funcao ou closure PHP.
     *
     * Formas aceitas:
     *   sentinel_monitor('job_id', function () { ... });
     *   sentinel_monitor('job_id', 'Nome do job', function () { ... });
     */
    function sentinel_monitor($jobId, $nameOrCallback, $callback = null, $serverUrl = null, $timeout = 5.0)
    {
        if (is_callable($nameOrCallback) && $callback === null) {
            $callback = $nameOrCallback;
            $name = null;
        } else {
            $name = $nameOrCallback;
        }

        if (!is_callable($callback)) {
            throw new InvalidArgumentException('O terceiro argumento deve ser uma funcao ou closure valida.');
        }

        $monitor = new SentinelMonitor($jobId, $name, $serverUrl, $timeout);
        return $monitor->run($callback);
    }
}

if (!function_exists('sentinel_fail')) {
    /**
     * Interrompe a rotina com uma falha que preserva a mensagem e o stack trace.
     * Util para substituir construcoes legadas como: DBQuery(...) or die(...)
     */
    function sentinel_fail($message)
    {
        throw new RuntimeException((string) $message);
    }
}
