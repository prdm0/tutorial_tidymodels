library(vetiver)
library(plumber)
library(pins)
library(callr)

# Regressão linear simples com mtcars
modelo <- lm(mpg ~ wt, data = mtcars)

# Modelo vetiver
modelo_vetiver <-
  vetiver::vetiver_model(
    model = modelo,
    model_name = "lm_mtcars_v1.0",
    description = "Modelo de regressão linear para prever mpg com wt"
  )

# Criando um board para pinar e versionar os modelos .rds
board <-
  pins::board_folder(
    path = "modelos",
    versioned = TRUE
  )

# Pinando o modelo no board
vetiver::vetiver_pin_write(
  board = board,
  vetiver_model = modelo_vetiver
)

# Criando e rodando a API rapidamente
# pr <- vetiver::vetiver_api(
#   pr = plumber::pr(),
#   vetiver_model = modelo_vetiver
# )
# pr$run(port = 8080)

# Criando um arquivo de configuração para a API
vetiver::vetiver_write_plumber(
  board,
  name = "lm_mtcars_v1.0",
  file = "api.r"
)

callr::r_bg(
  function() {
    pr <- plumber::plumb("api.r")
    pr$run(port = 8080)
  }
)

# Preparando o Dockerfile
vetiver::vetiver_prepare_docker(
  board,
  name = "lm_mtcars_v1.0",
  version = NULL,
  docker_args = list(port = 8000)
)
