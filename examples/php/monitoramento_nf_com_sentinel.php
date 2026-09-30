<?php
require_once __DIR__ . '/sentinel_monitor.php';

function monitoramentoNfUtf8DoBanco($texto){
	if($texto === null || $texto === ''){
		return '';
	}
	return utf8_encode($texto);
}

function monitoramentoNfFormatarMoeda($valor){
	if($valor === null || $valor === ''){
		return 'R$ 0,00';
	}
	return 'R$ ' . number_format((float)$valor, 2, ',', '.');
}

function monitoramentoNfFormatarData($data){
	if($data === null || trim((string)$data) === ''){
		return '';
	}
	$ts = strtotime($data);
	if($ts === false){
		return '';
	}
	return date('d/m/Y', $ts);
}

function monitoramentoNfSubstituirVariaveis($texto, $variaveis){
	foreach($variaveis as $chave => $valor){
		$texto = str_replace($chave, $valor, $texto);
	}
	return $texto;
}

function monitoramentoNfVariaveisNota($linha){
	return array(
		'{empresa_sigla}' => isset($linha['empSigla']) ? $linha['empSigla'] : '',
		'{cedente}' => isset($linha['nomeCedente']) ? $linha['nomeCedente'] : '',
		'{sacado}' => isset($linha['nomeSacado']) ? $linha['nomeSacado'] : '',
		'{chave_nota}' => isset($linha['chave']) ? $linha['chave'] : '',
		'{valor_nota}' => monitoramentoNfFormatarMoeda(isset($linha['nfValor']) ? $linha['nfValor'] : 0),
		'{num_NF}' => isset($linha['nfNum']) ? $linha['nfNum'] : '',
		'{data_hoje}' => date('d/m/Y'),
		'{data_monitoramento}' => monitoramentoNfFormatarData(isset($linha['dataMonitoramento']) ? $linha['dataMonitoramento'] : '')
	);
}

function monitoramentoNfVariaveisIngresso($linha){
	return array(
		'{empresa_sigla}' => isset($linha['empSigla']) ? $linha['empSigla'] : '',
		'{cedente}' => isset($linha['nomeCedente']) ? $linha['nomeCedente'] : '',
		'{sacado}' => isset($linha['nomeSacado']) ? $linha['nomeSacado'] : '',
		'{ingCodigo}' => isset($linha['ingresso']) ? $linha['ingresso'] : '',
		'{valor_de_face}' => monitoramentoNfFormatarMoeda(isset($linha['valordeFace']) ? $linha['valordeFace'] : 0),
		'{ingDocumento}' => isset($linha['documento']) ? $linha['documento'] : '',
		'{data_operacao}' => monitoramentoNfFormatarData(isset($linha['dataOpe']) ? $linha['dataOpe'] : ''),
		'{vencimento}' => monitoramentoNfFormatarData(isset($linha['vencimento']) ? $linha['vencimento'] : ''),
		'{data_hoje}' => date('d/m/Y'),
		'{data_monitoramento}' => monitoramentoNfFormatarData(isset($linha['dataMonitoramento']) ? $linha['dataMonitoramento'] : '')
	);
}

function monitoramentoNfLabelsCamposIngresso(){
	return array(
		'empresa_sigla' => 'Empresa',
		'ingCodigo' => 'Título',
		'valor_de_face' => 'Valor de Face',
		'ingDocumento' => 'Documento',
		'data_operacao' => 'Data de Operação',
		'vencimento' => 'Vencimento',
		'cedente' => 'Cedente',
		'sacado' => 'Sacado'
	);
}

function monitoramentoNfValorCampoIngresso($campo, $linha){
	switch($campo){
		case 'empresa_sigla':
			return htmlspecialchars(isset($linha['empSigla']) ? $linha['empSigla'] : '', ENT_QUOTES, 'UTF-8');
		case 'ingCodigo':
			return htmlspecialchars(isset($linha['ingresso']) ? $linha['ingresso'] : '', ENT_QUOTES, 'UTF-8');
		case 'valor_de_face':
			return monitoramentoNfFormatarMoeda(isset($linha['valordeFace']) ? $linha['valordeFace'] : 0);
		case 'ingDocumento':
			return htmlspecialchars(isset($linha['documento']) ? $linha['documento'] : '', ENT_QUOTES, 'UTF-8');
		case 'data_operacao':
			return monitoramentoNfFormatarData(isset($linha['dataOpe']) ? $linha['dataOpe'] : '');
		case 'vencimento':
			return monitoramentoNfFormatarData(isset($linha['vencimento']) ? $linha['vencimento'] : '');
		case 'cedente':
			return htmlspecialchars(isset($linha['nomeCedente']) ? $linha['nomeCedente'] : '', ENT_QUOTES, 'UTF-8');
		case 'sacado':
			return htmlspecialchars(isset($linha['nomeSacado']) ? $linha['nomeSacado'] : '', ENT_QUOTES, 'UTF-8');
		default:
			return '';
	}
}

function monitoramentoNfMontarTabelaIngressos($ingressos, $camposIngresso){
	if(empty($camposIngresso) || !is_array($camposIngresso)){
		return '';
	}

	$labels = monitoramentoNfLabelsCamposIngresso();
	$estiloTabela = 'font-family:Arial,sans-serif;border-collapse:collapse;font-size:13px;';
	$estiloTh = 'padding:4px 8px;text-align:left;border:1px solid #dee2e6;background:#f7f9fc;font-weight:600;font-size:13px;';
	$estiloTd = 'padding:4px 8px;text-align:left;border:1px solid #dee2e6;font-size:13px;';

	$html = '<table border="1" cellpadding="0" cellspacing="0" style="' . $estiloTabela . '">';
	$html .= '<tr>';

	foreach($camposIngresso as $campo){
		$titulo = isset($labels[$campo]) ? $labels[$campo] : $campo;
		$html .= '<th style="' . $estiloTh . '">' . htmlspecialchars($titulo, ENT_QUOTES, 'UTF-8') . '</th>';
	}

	$html .= '</tr>';

	foreach($ingressos as $linha){
		$html .= '<tr>';
		foreach($camposIngresso as $campo){
			$html .= '<td style="' . $estiloTd . '">' . monitoramentoNfValorCampoIngresso($campo, $linha) . '</td>';
		}
		$html .= '</tr>';
	}

	$html .= '</table>';
	return $html;
}

function monitoramentoNfObterEmailsCadastrados($conn, $eventoCodigo){
	$eventoCodigo = (int)$eventoCodigo;
	$query = "SELECT
		CASE
			WHEN COUNT(email) > 0
			THEN STRING_AGG(email, ';') + ';'
			ELSE ''
		END AS emailsCadastrados
		FROM intMonitoramentoEmailAviso
		WHERE monitoramentoEventoId = $eventoCodigo";
	$result = DBQuery($query, $conn) or sentinel_fail("Erro: ".DbError($conn)." na query <pre>$query</pre>");

	if(DbNumRows($result) > 0){
		$row = DbFetchAssoc($result);
		return isset($row['emailsCadastrados']) ? $row['emailsCadastrados'] : '';
	}

	return '';
}

function monitoramentoNfGerarMovimentacao($connMov, $linha, $eveCodigoMovimentacao, $instrucaoMovimentacao){
	$ingresso = (int)$linha['ingresso'];
	$empresa = (int)$linha['empresa'];
	$eveCodigo = (int)$eveCodigoMovimentacao;

	if($ingresso <= 0 || $empresa <= 0 || $eveCodigo <= 0){
		return;
	}

	$instrucao = monitoramentoNfSubstituirVariaveis(
		monitoramentoNfUtf8DoBanco($instrucaoMovimentacao),
		monitoramentoNfVariaveisIngresso($linha)
	);
	$instrucaoEscapada = str_replace("'", "''", $instrucao);
	$movCodigo = getProximoMovCodigo($empresa);

	$queryMov = "INSERT INTO nfMovimentacao (
			movCodigo, eveCodigo, empCodigo, movData, movDataOriginal, movValor, movDescricao, movIdentificaOrigem, movOrigem, movCedente, movUsuario,
			movDataInclusao, movHoraInclusao, movStatus, movDataProximoContrato, movValorInstrucao, movRetornoInstrucao)
		SELECT $movCodigo, $eveCodigo, $empresa, GETDATE(), GETDATE(), 0, '$instrucaoEscapada', 900, $ingresso, ing.cedCodigo, 'automacao', CAST(GETDATE() AS DATE),
			CAST(GETDATE() AS TIME), 'L', CAST(GETDATE() AS DATE), 0, 0
		FROM nfIngressos ing
		WHERE ing.ingCodigo = $ingresso AND ing.empCodigo = $empresa";

	DBQuery(utf8_decode($queryMov), $connMov) or sentinel_fail("Erro: ".DbError($connMov)." na query <pre>$queryMov</pre>");
}

function monitoramentoNfRegistrarControle($connControle, $netLogId){
	$netLogId = (int)$netLogId;
	if($netLogId <= 0){
		return;
	}

	$queryControle = "INSERT INTO MonitoramentoNfeMail (NetLogMonitoramentoNfeId) VALUES ($netLogId)";
	DBQuery($queryControle, $connControle) or sentinel_fail("Erro: ".DbError($connControle)." na query <pre>$queryControle</pre>");
}

function notificar($para, $assunto, $mensagem){
	$para = trim((string)$para);
	if($para === ''){
		return false;
	}

	$dados = array(
		'de' => 'checagem@sstars.com.br',
		'para' => $para,
		'assunto' => $assunto,
		'mensagem' => $mensagem
	);

	$resultadoEnvio = SendMail($dados);
	if($resultadoEnvio === false){
		sentinel_fail("Falha ao enviar o e-mail para: $para");
	}
	print "<pre>$mensagem\n</pre>";
	print "<pre>$para\n</pre>";
	return true;
}

function monitoramentoNfMontarDestinatarios($conn, $eventoCodigo, $enviarGestoresCarteira, $emailsGestores){
	$para = monitoramentoNfObterEmailsCadastrados($conn, $eventoCodigo);

	if((int)$enviarGestoresCarteira === 1 && trim((string)$emailsGestores) !== ''){
		$para .= $emailsGestores;
		if(substr($para, -1) !== ';'){
			$para .= ';';
		}
	}

	return $para;
}

function monitoramentoNfMontarMensagemEvento($configEvento, $ingressosGrupo){
	$primeiraLinha = $ingressosGrupo[0];
	$varsNota = monitoramentoNfVariaveisNota($primeiraLinha);

	$assuntoFinal = monitoramentoNfSubstituirVariaveis(
		monitoramentoNfUtf8DoBanco($configEvento['assunto']),
		$varsNota
	);

	$corpoFinal = monitoramentoNfSubstituirVariaveis(
		monitoramentoNfUtf8DoBanco($configEvento['corpoEmail']),
		$varsNota
	);

	$camposTabela = json_decode($configEvento['camposIngresso'], true);
	if(!is_array($camposTabela)){
		$camposTabela = array();
	}

	$tabelaHtml = '';
	if((int)$configEvento['exibirTabelaIngressos'] === 1 && !empty($camposTabela)){
		$tabelaHtml = monitoramentoNfMontarTabelaIngressos($ingressosGrupo, $camposTabela);
	}

	$corpoFinal = str_replace('{tabela_ingressos}', $tabelaHtml, $corpoFinal);

	return array(
		'assunto' => $assuntoFinal,
		'mensagem' => $corpoFinal
	);
}

function monitoramentoNfProcessarGrupoChave($conn, $connMov, $connControle, $configEvento, $ingressosGrupo){
	$ultimaLinha = $ingressosGrupo[count($ingressosGrupo) - 1];

	foreach($ingressosGrupo as $linha){
		if((int)$configEvento['gerarMovimentacao'] === 1){
			monitoramentoNfGerarMovimentacao(
				$connMov,
				$linha,
				$configEvento['eveCodigoMovimentacao'],
				$configEvento['instrucaoMovimentacao']
			);
		}

		monitoramentoNfRegistrarControle($connControle, $linha['netLogId']);
	}

	$para = monitoramentoNfMontarDestinatarios(
		$conn,
		$configEvento['evento'],
		$configEvento['enviarGestoresCarteira'],
		isset($ultimaLinha['emails']) ? $ultimaLinha['emails'] : ''
	);

	$mensagemEmail = monitoramentoNfMontarMensagemEvento($configEvento, $ingressosGrupo);
	notificar($para, $mensagemEmail['assunto'], $mensagemEmail['mensagem']);
}

function executarMonitoramentoNf(){
	if (!isset($GLOBALS['config'])){ 
		require '../config.php';
		require '../functions.php';
		require '../DBFunctions.php';
	}

	$conn = DbConect();
	$connMov = DbConect();
	$connControle = DbConect();
	$usuario = $_SESSION['usuario'];

	$query = "SELECT
	evento,
	assunto,
	corpoEmail,
	exibirTabelaIngressos,
	camposIngresso,
	enviarGestoresCarteira,
	gerarMovimentacao,
	eveCodigoMovimentacao,
	instrucaoMovimentacao,
	monitorarApartirDe
	FROM intMonitoramentoEvento
	WHERE ativo = 1";
	$result = DBQuery($query, $conn) or sentinel_fail("Erro: ".DbError($conn)." na query <pre>$query</pre>");

	while($configEvento = DbFetchAssoc($result)){
		$evento = isset($configEvento['evento']) ? trim($configEvento['evento']) : '';
		$monitorarApartirDe = isset($configEvento['monitorarApartirDe']) ? $configEvento['monitorarApartirDe'] : '';

		if($evento === ''){
			continue;
		}

		$monitorarApartirDeEscapado = str_replace("'", "''", $monitorarApartirDe);
		$eventoEscapado = str_replace("'", "''", $evento);

		$query = "SELECT ingresso, empresa, empSigla, nomeCedente, nomeSacado, chave, nfValor, nfNum, nfSerie, documento, valordeFace, dataOpe, vencimento, dataEmissao, netLogId, gdc, emails, dataMonitoramento,
		ROW_NUMBER() OVER (PARTITION BY chave ORDER BY chave) AS rn FROM (
				SELECT DISTINCT
				ce.id AS netLogId,
				ce.ingCodigo AS ingresso,
				ce.empcodigo AS empresa,
				emp.empSigla AS empSigla,
				pc.pesNome AS nomeCedente,
				ps.pesNome AS nomeSacado,
				ce.nlm_chaveRetorno AS chave,
				nfx.nfxValor AS nfValor,
				nfx.nfxNumero AS nfNum,
				nfx.nfxSerie AS nfSerie,
				ing.ingDocumento AS documento,
				ing.ingValordeFace AS valordeFace,
				ing.ingDataOpe AS dataOpe,
				ing.ingVencimento AS vencimento,
				nfx.nfxDataEmissao AS dataEmissao,
				gc.gdc_id AS gdc,
				emails.emails AS emails,
	            ce.nlm_data AS dataMonitoramento
			FROM NetLogMonitoramentoNfe ce
			LEFT JOIN MonitoramentoNfeMail nfm ON nfm.NetLogMonitoramentoNfeId = ce.id
			INNER JOIN netNotaFiscalXML nfx ON nfx.nfxChave = ce.nlm_chaveRetorno
			INNER JOIN nfIngressos ing ON ing.ingCodigo = ce.ingCodigo AND ing.empCodigo = ce.empCodigo
			INNER JOIN nfEmpresa emp ON emp.empCodigo = ing.empCodigo
			INNER JOIN nfCedente nc ON nc.cedCodigo = ing.cedCodigo AND nc.empCodigo = ing.empCodigo
			LEFT JOIN nfSacado ns ON ns.sacCodigo = ing.sacCodigo AND ns.empCodigo = ing.empCodigo
			LEFT JOIN nfPessoa pc ON pc.pesCNPJCPF = nc.pesCNPJCPF
			LEFT JOIN nfPessoa ps ON ps.pesCNPJCPF = ns.pesCNPJCPF
			LEFT JOIN netGestordeCarteira gc ON gc.gdc_id = nc.gdc_id
			OUTER APPLY (
				SELECT STRING_AGG(u.usuEmailSaldoContaVinculada, ';') emails
				FROM obUsuario u
				CROSS APPLY STRING_SPLIT(u.gdc_id, ',') AS split
				WHERE ISNULL(u.usuDesabilitado, 0) = 0
				AND split.value = gc.gdc_id
			) AS emails
			WHERE ce.nlm_codigoEventoRetorno = '$eventoEscapado'
			AND nfm.id IS NULL
			AND gc.gdc_inativo = 0
			AND ce.nlm_data >= '$monitorarApartirDeEscapado'
		) x
		ORDER BY chave, documento";

		$resultNotas = DBQuery($query, $conn) or sentinel_fail("Erro: ".DbError($conn)." na query <pre>$query</pre>");

		$rowsEvento = array();
		while($rowNota = DbFetchAssoc($resultNotas)){
			$rowsEvento[] = $rowNota;
		}

		if(empty($rowsEvento)){
			print "<pre>Não há registros para serem enviados (evento $evento)</pre>";
			continue;
		}

		$gruposPorChave = array();
		foreach($rowsEvento as $rowNota){
			$chaveGrupo = isset($rowNota['chave']) ? $rowNota['chave'] : '';
			if(!isset($gruposPorChave[$chaveGrupo])){
				$gruposPorChave[$chaveGrupo] = array();
			}
			$gruposPorChave[$chaveGrupo][] = $rowNota;
		}

		foreach($gruposPorChave as $ingressosGrupo){
			monitoramentoNfProcessarGrupoChave($conn, $connMov, $connControle, $configEvento, $ingressosGrupo);
		}
	}
}

sentinel_monitor(
	'monitoramento_nf_email',
	'Monitoramento de notas fiscais por e-mail',
	'executarMonitoramentoNf'
);

?>
