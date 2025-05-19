library(vetiver)
library(pins)

# Dados e modelo bem simples (sem tuning, só para exemplo)
modelo_lm <- lm(mpg ~ hp + wt, data = mtcars)

# Criar um objeto "vetiver" (nome do modelo: "modelo_lm")
v <- vetiver_model(model = modelo_lm, model_name = "modelo_lm_v1")

# Criar um board local (pasta)
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
vetiver_write_plumber(
  board,
  "modelo_lm_v1",
  file = "api_modelo.R",
  version = NULL # NULL = última versão
)

# Iniciar a API localmente (rodará na porta 8080)
pr <- plumber::plumb("api_modelo.R")
# Executando a API: pr$run(port = 8080)
