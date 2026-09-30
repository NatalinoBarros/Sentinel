<?php
require_once __DIR__ . '/../sentinel_monitor.php';

//ESSE É O VALIDO NO AGENDAMENTO
$GLOBALS['prodForcado'] = true;
require '../../config.php';
require '../../functions.php';
require '../../DBFunctions.php';
//
function executarRetornoBancarioGrafeno(){
	$conn = DbConect();
	$GLOBALS['conn'] = $conn;
	$and = '';
	$datas = array();
	$cccCodigo = null;
	extract($_GET);
	//
	if(isset($_GET['empCodigo']) && $_GET['empCodigo']){
		$and = " and e.empCodigo='".$_GET['empCodigo']."'";
	}
	//
	$arrayLog = array();
	$queryToken = "SELECT top 1 e.empCodigo, e.empSigla, t.token_codigo FROM intTokens t 
					inner join nfEmpresa e on t.empCodigo=e.empCodigo
					WHERE token_servico='Grafeno' and apiAmbiente='Produção' $and
					ORDER BY e.empCodigo";
	$resultToken = DBQuery(utf8_decode($queryToken), $GLOBALS['conn']) or sentinel_fail("Erro: ".DbError($GLOBALS['conn'])." na query: <pre> $queryToken </pre>");
	if(DbNumRows($resultToken)){
		extract(DbFetchAssoc($resultToken));
		$GLOBALS['GrafenoToken'] = $token_codigo;
		$GLOBALS['EmpToken'] = $empCodigo;
		$GLOBALS['EmpSigla'] = $empSigla;
	}
	else {
		sentinel_fail('Nenhum token de produção da Grafeno foi encontrado.');
	}
	//
	$data = (!isset($data)) ? date("Y-m-d") : $data;
	$time = 5000;
	$query = "SELECT TOP 2 cast(Dt_Referencia as date) Data from Dia_Util D where D.Fl_Dia_Util='1' and Dt_Referencia <= '$data' order by Dt_Referencia desc";
	//$query = "SELECT top 2 cast(Dt_Referencia as date) Data from Dia_Util D where D.Fl_Dia_Util='1' and Dt_Referencia<='2025-12-31' order by Dt_Referencia desc";

	$result = DBQuery($query, $conn) or sentinel_fail("(getArquivosRetornos) Erro: ".DbError($conn)." na query <pre>$query</pre>");
	//print $query."<br>";
	while($r = DbFetchAssoc($result)){
		extract($r);
		$datas[] = $Data;
	}

	$pag = (!isset($pag)) ? 1 : $pag;
	$url = $GLOBALS['GrafenoUrlBaseV2']."ip_bank_accounts?p[per_page]=2&p[page]=$pag"; //criado > que


	// print($url);
	// return;
	//
	$header = array(
						"Authorization: ".$GLOBALS['GrafenoToken'],
						"accept: application/json"
					 );
	$curl = REST(array(
						'url'	 => $url,
						'method' => 'GET',
						'header' => $header,
						'postData' => array(),
					  )
				);
	extract($curl);
	//print "<pre>".print_r($curl,true)."</pre>";
	//return;
	//Em caso de falha
	if ($err) {
		
		$dados = Array(	'mensagem'	=>	"<pre>Endpoint: " . $url . "</pre><br>\r\n
										 <pre>URL: " . $GLOBALS['fullURL'] . "</pre><br>\r\n
										 <pre>Header: " . print_r($header, true) . "</pre>\r\n
										 <pre>Retornor :" . $retorno . "</pre>\r\n
										 <pre>Resposta :" . print_r($response, true) . "</pre>\r\n
										 <pre>cURL Error #:" . $err . "</pre><br>\r\n",
						'de' 		=> 'sistemas@sstars.com.br',
						'para' 		=> 'sistemas@sstars.com.br;financeiro@sstars.com.br',
						'assunto'	=> 'API da Grafeno - Arquivo Retorno - Erro ao requisitar contas' 
					  );
		SendMail($dados);
		sentinel_fail($dados['assunto']);
		print $dados['mensagem'];
		Novamente($time*2);
		//ProximaPagina($pag, $time);
		
	} else {
		$http_response_header = explode("\r\n",$response);
		$retorno = $http_response_header[0]; 
		$response = json_decode(end($http_response_header));
		
		//Se status da consulta for sucesso
		if ($http_code >= 200 && $http_code < 300){
			
			print "<pre>\r\n";
			print "URL: " . $url . "<br>\r\n";
			print_r($response);
			print "</pre>\r\n";
			//$arrayLog[] = "URL: " . $url . "<br>\r\n";
			//return;

			$dir_log_grafeno = 'C:\\logs_grafeno\\';
			if (!is_dir($dir_log_grafeno)) {
				mkdir($dir_log_grafeno, 0777, true);
			}
			$log_name = date("d_m_y") . '.log';
			$conteudo_log = "URL: " . $url . "\r\n" . "RESPOSTA: ".print_r($response, true)."\r\n" . PHP_EOL;
	        $pathLog = $dir_log_grafeno . $log_name;
	       
	        $file_log = fopen($pathLog, "a");
	        if ($file_log === false) {
	            sentinel_fail("Erro ao abrir o arquivo de log: " . $pathLog);
	        }              
	        fwrite($file_log, $conteudo_log);
	        fclose($file_log);


			$nextPage = $response->meta->pagination->nextPage;
			foreach($response->data as $conta){ // Fazendo um for Pegando conta a conta dentro do array $response->data
				for($i=0; $i<count($datas); $i++){ // Fazendo um for Pegando data a data dentro do array $datas

					$cccConta = str_replace('-','',$conta->attributes->account);
					$dataRetorno = $datas[$i];
					$urlR = $GLOBALS['GrafenoUrlBaseV2']."cnab?q[dateEq]=".$dataRetorno."&q[accountNumberEq]=".$conta->attributes->account;
					// $urlR = $GLOBALS['GrafenoUrlBaseV2']."cnab?p[page]=$pag&q[dateEq]=".$dataRetorno; //."&q[accountNumberEq]=".$cccConta;
					//$urlR = $GLOBALS['GrafenoUrlBaseV2']."cnab?q[dateEq]=".$dataRetorno; //."&q[accountNumberEq]=".$cccConta;
					//
					
					$query = "SELECT cccCodigo from nfContaCorrenteCaixa where empCodigo='".$GLOBALS['EmpToken']."' and cccConta='$cccConta'";
					$result = DBQuery($query, $conn) or sentinel_fail("Erro: ".DbError($conn)." na query <pre>$query</pre>");
					if(DbNumRows($result)){
						extract(DbFetchAssoc($result));
					}else { 
						print "<pre>CONTA: ".$conta->attributes->account." de ".$conta->attributes->companyName." não utilizada no Netfactor.</pre>\r\n";
					}
					//

					$header = array("Authorization: ".$GLOBALS['GrafenoToken'],"Account-Number: ".$conta->attributes->account,"accept: application/json");
					print("<pre>");
					print("URL: ".$urlR."<br>");
					print("CONTA: ".$conta->attributes->account."\r\n");
					print("HEADER: ".print_r($header, true)."\r\n");
					print("</pre>");

					$dir_log_grafeno = 'C:\\logs_grafeno\\';
			        if (!is_dir($dir_log_grafeno)) {
			        	mkdir($dir_log_grafeno, 0777, true);
			        }
			        $log_name = date("d_m_y") . '.log';
			        $conteudo_log = "URL: " . $urlR . "\r\n" . "CONTA: ".$conta->attributes->account."\r\n" . "HEADER: ".print_r($header, true)."\r\n " . PHP_EOL;
	                $pathLog = $dir_log_grafeno . $log_name;
	               
	                $file_log = fopen($pathLog, "a");
	                if ($file_log === false) {
	                    sentinel_fail("Erro ao abrir o arquivo de log: " . $pathLog);
	                }              
	                fwrite($file_log, $conteudo_log);
	                fclose($file_log);
				
					
					$curl = REST(array('url'=> $urlR,'method' => 'GET','header' => $header,'postData' => array(),));
					extract($curl);
					/*
					$http_response_header = explode("\r\n",$response);
					$retorno = $http_response_header[0]; //(strpos($http_response_header[0], "Continue")>0)?$http_response_header[2]:$http_response_header[0];
					$response = json_decode(end($http_response_header));
					print "<pre>\r\n";
					print "URL: " . $url . "<br>\r\n";
					print "Header: " . print_r($header, true) . "<br>\r\n";
					print "Retorno: " . print_r($response, true) . "<br>\r\n";
					print "</pre>\r\n";
					*/
					if($err){
						$dados = Array(	'mensagem'	=>	"<pre>Endpoint: " . $urlR . "</pre><br>\r\n
														<pre>URL: " . $GLOBALS['fullURL'] . "</pre><br>\r\n
														<pre>Header: " . print_r($header, true) . "</pre>\r\n
														<pre>Retornor :" . $retorno . "</pre>\r\n
														<pre>Resposta :" . print_r($response, true) . "</pre>\r\n
														 <pre>cURL Error #:" . $err . "</pre><br>\r\n",
										'de' 		=> 'sistemas@sstars.com.br',
										'para' 		=> 'sistemas@sstars.com.br;financeiro@sstars.com.br',
										'assunto' 	=> 'API da Grafeno - Arquivo Retorno - Falha ao requisitar arquivos retorno' 
									  );
						SendMail($dados);
					sentinel_fail($dados['assunto']);
						print $dados['mensagem'];
						Novamente($time*2);
						return;
						//
					}else {
						$http_response_header = explode("\r\n",$response);
						$retorno = $http_response_header[0]; //(strpos($http_response_header[0], "Continue")>0)?$http_response_header[2]:$http_response_header[0];
						$response = json_decode(end($http_response_header));
						//
						if ($http_code >= 200 && $http_code < 300){
							//print "<pre>\r\n";
							//print "URL: " . $urlR . "<br>\r\n";
							//print "CONTA: ".$conta->attributes->accountNumber."<br>\r\n";
							////print_r($response, true);
							//print "Baixando retorno da conta ".$conta->attributes->accountNumber." de ".$conta->attributes->accountName." em ".date("d/m/Y", strtotime($dataRetorno))."<br>\r\n";
							//print "</pre>\r\n";
							//
							// print("<pre>");
							// print_r($response);
							// print("</pre>");

							//$nextPage = $response->meta->pagination->nextPage;
							//
							//return;
							foreach($response->data as $files){
								$fileId = $files->id;
								$link = $files->attributes->file;
								$filename = $files->attributes->filename;
								$accountNumber = $files->attributes->accountNumber;
								$accountName = $files->attributes->accountName;
								$cnabao = file_get_contents($link);
								if ($cnabao === false) {
									sentinel_fail("Falha ao baixar o arquivo remoto: " . $link);
								}
								//
								$loc_ret = "Retornos/".trim($accountNumber);
								$loc_ret_proc = "Retornos/Processamento";
								// $loc_ret_proc_van = "c:\\integracao bancaria\\COBRANCA\\".$GLOBALS['EmpSigla']."\\GRAFENO\\".trim($accountNumber);
								$loc_ret_proc_van = "c:\\integracao bancaria\\COBRANCA\\SEC\\GRAFENO\\".trim($accountNumber);
								//
								$dir_ret = "\\\\srv-stars01\\FILESERVER\\Publico\\INTEGRAÇÃO BANCÁRIA\\GRAFENO\\Retorno\\".trim($accountNumber);
								$dir_ret_proc = "\\\\srv-stars01\\FILESERVER\\Publico\\INTEGRAÇÃO BANCÁRIA\\GRAFENO\\Retorno\\Processamento";
								// $dir_ret_proc_van = "c:\\integracao bancaria\\COBRANCA\\".$GLOBALS['EmpSigla']."\\GRAFENO\\".trim($accountNumber)."\Retorno";
								$dir_ret_proc_van = "c:\\integracao bancaria\\COBRANCA\\SEC\\GRAFENO\\".trim($accountNumber)."\Retorno";
								//
								
								//
								if(!is_dir($loc_ret_proc_van)){
									print("Pasta Não existe: ".$loc_ret_proc_van."<br>");
									print("Criando pasta: ".$loc_ret_proc_van."<br>");
									mkdir($loc_ret_proc_van);
									mkdir($loc_ret_proc_van."\\Remessa/");
									mkdir($loc_ret_proc_van."\\Retorno/");
									mkdir($loc_ret_proc_van."\\Retorno/Importados");
									mkdir($loc_ret_proc_van."\\Retorno/Importados/CNAB");
									mkdir($loc_ret_proc_van."\\Retorno/Importados/PDF");

								}
							
								if(!is_dir($loc_ret)){
										mkdir($loc_ret);
								}
								
								if(!is_dir($loc_ret_proc)){
										mkdir($loc_ret_proc);
								}
								
								if(!is_dir($dir_ret)){
										mkdir($dir_ret);
								}
								
								$dataf = str_replace('-', '', $dataRetorno);
								$arq_ret = $accountNumber.'_'.$dataf.'_'.$fileId.'.ret';
								
								$pathArquivo = $loc_ret.'\\'.$arq_ret;
								$pathArquivoRede = $dir_ret.'\\'.$arq_ret;
								// print "<pre>Baixando o arquivo $pathArquivo.</pre>\r\n";
								//
								print("<pre>");
								print("ARQUIVO: ".$arq_ret."<br>");
								print("</pre>");
								$dir_log_grafeno = 'C:\\logs_grafeno\\';
			                    if (!is_dir($dir_log_grafeno)) {
			                    	mkdir($dir_log_grafeno, 0777, true);
			                    }
			                    $log_name = date("d_m_y") . '.log';
			                    $conteudo_log = "ARQUIVO: " . $arq_ret . "\r\n" . "CAMINHO DO ARQUIVO: " . $pathArquivo . "\r\n ============================================\r\n" . PHP_EOL;
	                            $pathLog = $dir_log_grafeno . $log_name;
	                           
	                            $file_log = fopen($pathLog, "a");
	                            if ($file_log === false) {
	                                sentinel_fail("Erro ao abrir o arquivo de log: " . $pathLog);
	                            }              
	                            fwrite($file_log, $conteudo_log);
	                            fclose($file_log);


								
								$file = fopen($pathArquivo, "wb");
								if ($file === false) {
									sentinel_fail("Erro ao criar o arquivo de retorno: " . $pathArquivo);
								}
								if (fwrite($file, $cnabao) === false) {
									fclose($file);
									sentinel_fail("Erro ao gravar o arquivo de retorno: " . $pathArquivo);
								}
								fclose($file);
								//
								//Copiar arquivo para pasta de processamento local - rateio
								if (!copy($pathArquivo, $loc_ret_proc.'\\'.$arq_ret)) {
									sentinel_fail("Falha ao copiar $pathArquivo para rateio " . $loc_ret_proc . "\\" . $arq_ret);
								}
								
								//Copiar arquivo para pasta de publico
								if (!copy($pathArquivo, $dir_ret.'\\'.$arq_ret)) {
									sentinel_fail("Falha ao copiar $pathArquivo para público " . $dir_ret . "\\" . $arq_ret);
								}
								
								//Copiar arquivo para pasta de processamento publico - rateio
								if (!copy($pathArquivo, $dir_ret_proc.'\\'.$arq_ret)) {
									sentinel_fail("Falha ao copiar $pathArquivo para público/rateio " . $dir_ret_proc . "\\" . $arq_ret);
								}

								// $pathBancario = "c:\\integracao bancaria\\COBRANCA\\".$GLOBALS['EmpSigla']."\\GRAFENO\\".trim($accountNumber)."\\Retorno\\Importados\\CNAB\\$arq_ret";
								$pathBancario = "c:\\integracao bancaria\\COBRANCA\\SEC\\GRAFENO\\".trim($accountNumber)."\\Retorno\\Importados\\CNAB\\$arq_ret"; // Verifica se o arquivo já foi importado.
								$log_info = "Baixando o arquivo".$pathArquivo."";	
								if(is_file($pathBancario)){
									print("Arquivo já importado: ".$pathBancario."<br>");	
									$log_info = "Arquivo já importado: ".$pathBancario." ";				
								}else{
									if (!copy($pathArquivo, $dir_ret_proc_van."\\".$arq_ret)) {
										sentinel_fail("Falha ao copiar $pathArquivo para pasta " . $dir_ret_proc_van . "\\" . $arq_ret);
										#$log_info = "falha ao copiar $pathArquivo para pasta ".$dir_ret_proc_van."\\".$arq_ret." ";	
									}
								}

								
								// SISTEMA DE LOG SINISTRO IMPROVISADO (NÃO FAZER NADA AQUI) \\
								$dir_log_grafeno = 'C:\\logs_grafeno\\' . trim($accountNumber) . '\\log\\';
	                            if (!is_dir($dir_log_grafeno)) {
	                                mkdir($dir_log_grafeno, 0777, true);
	                            }
	                            $log_name = date("d_m_y_H") . '.log';
	                            $conteudo_log = "NOME DO ARQUIVO: " . $arq_ret . " HORA DO DOWNLOAD: " . date("d/m/Y H:i:s")." " . $log_info . PHP_EOL;
	                            $pathLog = $dir_log_grafeno . $log_name;
	                            //print("LOG DOWNLOAD <br>");
	                            //print($pathLog . "<br>");
	                            $file_log = fopen($pathLog, "a");
	                            if ($file_log === false) {
	                                sentinel_fail("Erro ao abrir o arquivo de log: " . $pathLog);
	                            }
	                            
	                            fwrite($file_log, $conteudo_log);
	                            fclose($file_log);
								// SISTEMA DE LOG SINISTRO IMPROVISADO \\

								/*
								$query = "SELECT * from intImportacaoRetorno where cccCodigo='$cccCodigo' and dataArquivo='$dataRetorno' and pathArquivo='".utf8_decode($pathArquivoRede)."'";
								$result = DBQuery($query, $conn) or sentinel_fail("(getArquivosRetornos) Erro: ".DbError($conn)." na query <pre>$query</pre>");
								//
								if(DbNumRows($result)==0){
									$query = "INSERT into intImportacaoRetorno (cccCodigo, pathArquivo, dataArquivo) values ('$cccCodigo', '".utf8_decode($pathArquivoRede)."', '$dataRetorno')";
									$result = DBQuery($query, $conn) or sentinel_fail("(getArquivosRetornos) Erro: ".DbError($conn)." na query <pre>$query</pre>");
									print "<pre>Arquivo $arq_ret salvo am banco para importação.</pre>\r\n";
								}
								*/
							}
						}
						else {
							if($http_code == 403){
								print "<pre>Acesso negado ao arquivo: ".$url.", verifique se a conta está habilitada para download de arquivos retorno.</pre>\r\n";
							}
							else {
								$dados = Array(	'mensagem'	=>	"<pre>Endpoint: " . $url . "</pre>\r\n
																<pre>URL: " . $GLOBALS['fullURL'] . "</pre>\r\n
																<pre>Header: " . print_r($header, true) . "</pre>\r\n
																<pre>Retorno :" . $retorno . "</pre>\r\n
																<pre>Resposta :" . print_r($response, true) . "</pre>\r\n",
												'de' 		=> 'sistemas@sstars.com.br',
												'para' 		=> 'sistemas@sstars.com.br;financeiro@sstars.com.br',
												'assunto' 	=> 'API da Grafeno - Arquivo Retorno - Problema ao baixar arquivo retorno' 
										);
								SendMail($dados);
								sentinel_fail($dados['assunto']);
								print $dados['mensagem'];
								Novamente($time*2);
								return;
							}
						}
					}
					
				}
				//print "Aguardando 3 segundos...";
				//sleep(3);
			}
			
			if(!$cccCodigo || !$nextPage){
				//verificar se existe token para outra empresa
				$queryToken = "SELECT top 1 e.empCodigo, e.empSigla, t.token_codigo FROM intTokens t 
					inner join nfEmpresa e on t.empCodigo=e.empCodigo
					WHERE token_servico='Grafeno' and apiAmbiente='Produção' and e.empCodigo > '".$GLOBALS['EmpToken']."'
					ORDER BY e.empCodigo";
				$resultToken = DBQuery(utf8_decode($queryToken), $GLOBALS['conn']) or sentinel_fail("Erro: ".DbError($GLOBALS['conn'])." na query: <pre> $queryToken </pre>");
				print "<pre>".$queryToken."</pre>";
				if(DbNumRows($resultToken)){
					extract(DbFetchAssoc($resultToken));
					ProximaPagina($pag=0, $time, $empCodigo);
					return;
				}
				else {
					print "<pre>Processamento concluído.</pre>";
					return;
				}
			}
			else{
				if($nextPage>0){
					ProximaPagina($pag, $time);
					return;
				}
				else{
					print "<pre>Processamento concluído.</pre>";
					return;
				}
			}
		}
		else {
			$dados = Array(	'mensagem'	=>	"<pre>Endpoint: " . $url . "</pre><br>\r\n
											<pre>URL: " . $GLOBALS['fullURL'] . "</pre><br>\r\n
											<pre>Header: " . print_r($header, true) . "</pre>\r\n
											<pre>Retornor :" . $retorno . "</pre>\r\n
											<pre>Resposta :" . print_r($response, true) . "</pre>\r\n",
							'de' 		=> 'sistemas@sstars.com.br',
							'para' 		=> 'sistemas@sstars.com.br',
							'assunto' 	=> 'API da Grafeno - Arquivo Retorno - Problema ao listar contas disponiveis' 
					  );
			SendMail($dados);
			sentinel_fail($dados['assunto']);
			print $dados['mensagem'];
			Novamente($time*2);
			return;
			//ProximaPagina($pag, $time);
		}
	}
}

sentinel_monitor(
	'Retorno_Bancario_Grafeno',
	'Processamento Rateio (Grafeno)',
	'executarRetornoBancarioGrafeno'
);

function Novamente($time){
	// TENTAR NOVAMENTE POIS DEU ERRO
	print "
	<script>
		setTimeout(function(){self.location = location.href;},$time);
	</script>
	";
}

function ProximaPagina($pag, $time, $empCodigo=null){
	// IR PARA A PROXIMA PAGINA
	$pag++;
	$empCod = ($empCodigo>0) ? $empCodigo : (isset($_GET['empCodigo']) ? $_GET['empCodigo'] : null);
	$url = "http://" . $_SERVER['HTTP_HOST'] . $_SERVER['URL'] . '?pag=' . $pag;
	$url .= (isset($_GET['data'])) ? '&data=' . $_GET['data'] : '';
	$url .= ($empCod) ? '&empCodigo=' . $empCod : '';

	print "
	<script>
		setTimeout(function(){self.location = '$url';},$time);
	</script>
	";
}
?>
