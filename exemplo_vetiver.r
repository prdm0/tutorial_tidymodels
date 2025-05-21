library(vetiver)
library(pins)
library(callr)

rm(list = ls())

# Dados e modelo bem simples (sem tuning, só para exemplo)
modelo_lm <- lm(mpg ~ hp + wt, data = mtcars)

# Criar um objeto "vetiver" (nome do modelo: "modelo_lm")
v <- vetiver_model(
  model = modelo_lm,
  model_name = "modelo_lm_v1"
)

# Criar um board local (pasta) com modelos em .rds
board <- board_folder("modelos", versioned = TRUE)

# Pinar o modelo no board
vetiver_pin_write(board = board, vetiver_model = v)

# Verificar o que está no board
pin_list(board) # Deve mostrar "modelo_lm"

# Verificando detalhes das versões
pin_versions(board, "modelo_lm_v1")

vetiver_pin_read(
  board,
  "modelo_lm_v1"
)

# Gerar o arquivo da API
# vetiver_write_plumber(
#   board,
#   "modelo_lm_v1",
#   file = "api_modelo.R",
#   version = NULL # NULL = última versão
# )

# Iniciar a API localmente (rodará na porta 8080)
# lsof -i :8080 (verificando se a porta 8080 está livre em Linux e Mac)
# Matando um processo: kill -9 <PID> (Linux e Mac)
# callr::r_bg(
#   function() {
#     pr <- plumber::plumb("api_modelo.R")
#     pr$run(port = 8080)
#   }
# )

# Espera um tempo até o servidor plumber estar ativo para receber
# requisições. O tempo pode variar dependendo do computador.
# Sys.sleep(5)

# Criando um endpoint para fazer previsões
# endpoint <- vetiver_endpoint("http://127.0.0.1:8080/predict")
# Verificando o protótipo do endpoint
# vetiver_ptype(modelo_lm, TRUE)
# previsao <- predict(
#   endpoint,
#   new_data = data.frame(hp = c(100, 150), wt = c(2.5, 3.0))
# )

# Verificando o resultado
# print(previsao)

# Criando Dockerfile
vetiver_prepare_docker(
  board,
  "modelo_lm_v1",
  docker_args = list(port = 8080)
)
