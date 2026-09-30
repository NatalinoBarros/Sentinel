<?php

require_once __DIR__ . '/../../client/sentinel_monitor.php';

sentinel_monitor(
    'exemplo_php_falha',
    'Exemplo PHP com falha',
    function () {
        sentinel_fail('Falha simulada na rotina PHP.');
    }
);
