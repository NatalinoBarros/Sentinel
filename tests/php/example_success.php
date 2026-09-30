<?php

require_once __DIR__ . '/../../client/sentinel_monitor.php';

$result = sentinel_monitor(
    'exemplo_php_sucesso',
    'Exemplo PHP com sucesso',
    function () {
        echo "Processando rotina PHP...\n";
        return 42;
    }
);

echo "Resultado: " . $result . "\n";

