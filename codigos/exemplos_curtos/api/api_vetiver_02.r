library(vetiver)
library(plumber)
library(pins)
library(callr)

# Modelo mtcars (modelo de regresión lineal)
modelo <- lm(mpg ~ wt + hp, data = mtcars)

# Criando o modelo vetiver
modelo_vetiver <- vetiver::vetiver_model(
  model = modelo,
  model_name = "lm_v2.0",
  description = "Modelo de regressão linear para prever mpg com wt e hp"
)

# Criando um reposítório local de pins
pins::board_folder(
  path = "modelos",
  versioned = TRUE
)

# Escrevendo no board (pinando o modelo)
vetiver::vetiver_pin_write(board, modelo_vetiver)

# Rodando a API sem muito mistério
# api <- vetiver::vetiver_api(plumber::pr(), modelo_vetiver)
# api$run(port = 8080)

# Criando o arquivo plumber.R
vetiver::vetiver_write_plumber(board, "lm_v2.0", file = "api.r")

callr::r_bg(
  function() {
    pr <- plumber::plumb("api.r")
    pr$run(port = 8080)
  }
)

# Preparando Dockerfile

vetiver::vetiver_prepare_docker(
  board,
  name = "lm_v2.0",
  version = NULL,
  docker_args = list(port = 8080)
)
