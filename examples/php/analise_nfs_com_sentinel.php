<?php
require_once __DIR__ . '/sentinel_monitor.php';

if (!isset($GLOBALS['config'])){ 
    require '../../config.php';
    require '../../functions.php';
    require '../../DBFunctions.php';
    require '../TCPDF-main/examples/tcpdf_include.php';
}
require_once '../vendor/autoload.php';
include_once '../../iNET/php/IAfunctions.php';
include_once 'NFs_Params.php';
include_once 'processaRetorno.php';

set_time_limit(0);
ignore_user_abort(true);
@ini_set('zlib.output_compression', 0);
while (ob_get_level() > 0) { ob_end_flush(); }
@ob_implicit_flush(true);

$modoCLI = (php_sapi_name() == 'cli');
$ciclo = isset($_GET['ciclo']) ? (int) $_GET['ciclo'] : 1;
$preparado = (isset($_GET['preparado']) && $_GET['preparado'] == '1');
$estadoAnterior = isset($_GET['estado']) ? $_GET['estado'] : '';

// Em linha de comando não existe timeout de requisição, então o volume inteiro roda de uma vez
$prazoProcessamento = $modoCLI ? 0 : (time() + $tempoPorCiclo);

function Descarregar(){ // Empurra a saida ja impressa para o navegador durante o processamento
    print str_pad('', 4096) . "\n";
    @flush();
}

function ContinuarEmOutraRequisicao($proximoCiclo, $preparado, $estado){
    $url = 'analiseNFs.php?ciclo=' . $proximoCiclo . '&preparado=' . ($preparado ? '1' : '0') . '&estado=' . urlencode($estado);
    print '<p><b>Tempo do ciclo esgotado. Continuando no ciclo ' . $proximoCiclo . '...</b></p>';
    print '<meta http-equiv="refresh" content="0;url=' . htmlspecialchars($url) . '">';
    print '<script>window.location.replace(' . json_encode($url) . ');</script>';
    Descarregar();
}

function ExecutarCiclo($preparado){ // Devolve o estado do ciclo: se a preparação terminou e se ainda restam arquivos

    global $arrayLimite;
    global $timeOut;

    if(!$preparado){

        ExtrairArquivosOrigem();
        ExtrairConteudo();
        Descarregar();

        if(!PrepararArquivos()){
            return ['preparado' => false, 'interrompido' => true];
        }

        $preparado = true;
    }

    $arquivosValidacao = ObtemPrimeiraPagina();
    $arquivos = ListarArquivosProntos();

    // EXTRACAO DOS DADOS DAS NOTAS, EM LOTES
    $total = count($arquivos);
    $duracaoUltimaChamada = 0;
    $trabalhou = false;
    print '<b>Extração:</b> ' . $total . ' arquivo(s) na fila.<br>';
    Descarregar();

    for ($i = 0; $i < $total; $i += $arrayLimite) {

        // O lote seguinte só começa se couber no tempo restante, senão a requisição seria derrubada no meio dele.
        // Ao menos um lote roda por ciclo, do contrário a fila nunca andaria
        if ($trabalhou && PrazoInsuficiente($duracaoUltimaChamada + $timeOut)) {
            return ['preparado' => true, 'interrompido' => true];
        }

        $lote = array_slice($arquivos, $i, $arrayLimite);
        $numeroLote = floor($i / $arrayLimite) + 1;

        print 'Lote ' . $numeroLote . ' - enviando ' . count($lote) . ' arquivo(s)...<br>';
        Descarregar();

        $inicioChamada = time();

        try {
            TratarRetornoExtracao(ExtrairDadosNotaLote($lote));
        } catch (Throwable $e) {
            print 'Erro no lote ' . $numeroLote . ': ' . $e->getMessage() . '<br>';
            throw new RuntimeException(
                'Falha no lote ' . $numeroLote . ': ' . $e->getMessage(),
                0,
                $e
            );
        }

        $duracaoUltimaChamada = max($duracaoUltimaChamada, time() - $inicioChamada);
        $trabalhou = true;
        Descarregar();

        if ($i + $arrayLimite < $total) {
            sleep($timeOut);
        }
    }

    // VALIDACAO DOS ARQUIVOS COM MUITAS PAGINAS, UM A UM
    print '<b>Validação:</b> ' . count($arquivosValidacao) . ' arquivo(s) na fila.<br>';
    Descarregar();

    $duracaoUltimaChamada = 0;

    foreach ($arquivosValidacao as $item) {

        if ($trabalhou && PrazoInsuficiente($duracaoUltimaChamada)) {
            return ['preparado' => true, 'interrompido' => true];
        }

        print 'Validando ' . $item['arquivo'] . '...<br>';
        Descarregar();

        $inicioChamada = time();

        try {
            $item['isNFS'] = ConfirmarSeEhNota($item['temp']);
            TratarRetornoValidacao([$item]);
        } catch (Throwable $e) {
            print 'Erro ao validar ' . $item['arquivo'] . ': ' . $e->getMessage() . '<br>';
            throw new RuntimeException(
                'Falha ao validar ' . $item['arquivo'] . ': ' . $e->getMessage(),
                0,
                $e
            );
        }

        $duracaoUltimaChamada = max($duracaoUltimaChamada, time() - $inicioChamada);
        $trabalhou = true;
        Descarregar();
    }

    // Os arquivos aprovados na validacao acabaram de entrar na fila de entrada e são preparados para a próxima passagem
    PrepararArquivos();

    return ['preparado' => true, 'interrompido' => false];
}

function executarAnaliseNFs(){
    global $modoCLI, $ciclo, $preparado, $estadoAnterior, $ciclosMaximos;

    while (true) {

        print '<p><b>Ciclo ' . $ciclo . '</b> iniciado às ' . date('H:i:s') . '</p>';
        Descarregar();

        $resultado = ExecutarCiclo($preparado);
        $preparado = $resultado['preparado'];

        $estadoAtual = EstadoFila();
        $restantes = count(ListarFilaPendente());

        if (!$resultado['interrompido'] && $restantes == 0) {
            print '<br><b>Processamento concluído.</b><br>';
            break;
        }

        // Mesma fila do ciclo anterior significa que os arquivos restantes não avançam, então parar evita repetir para sempre
        if ($estadoAtual === $estadoAnterior) {
            $mensagem = 'Processamento encerrado: ' . $restantes . ' arquivo(s) não avançaram no último ciclo.';
            print '<br><b>' . $mensagem . '</b><br>';
            sentinel_fail($mensagem);
        }

        if ($ciclo >= $ciclosMaximos) {
            $mensagem = 'Processamento encerrado: limite de ' . $ciclosMaximos . ' ciclos atingido com ' . $restantes . ' arquivo(s) na fila.';
            print '<br><b>' . $mensagem . '</b><br>';
            sentinel_fail($mensagem);
        }

        $estadoAnterior = $estadoAtual;
        $ciclo++;

        if (!$modoCLI) {
            ContinuarEmOutraRequisicao($ciclo, $preparado, $estadoAtual);
            return;
        }
    }
}

sentinel_monitor(
    'Analise_NFs',
    'Análise e validação de notas fiscais',
    'executarAnaliseNFs'
);

?>
