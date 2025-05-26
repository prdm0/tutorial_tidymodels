library(vetiver)
library(pins)

# Criando uma regressão linear simples com iris
modelo <- lm(Sepal.Length ~ Sepal.Width, data = iris)

# Definindo o modelo vetiver
modelo_vetiver <- vetiver::vetiver_model(
  model = modelo,
  model_name = "modelo_lm"
)

# Criar um board com o pacote pins para versionar o modelo
board <- pins::board_folder("modelos", versioned = TRUE)

# Escrevendo o modelo no board
vetiver::vetiver_pin_write(
  board = board,
  vetiver_model = modelo_vetiver
)

# Criando o arquivo da api
# api <- vetiver::vetiver_api(plumber::pr(), modelo_vetiver)
# plumber::pr_run(api)

# Criando um arquivo para a API (arquivo plumber)

vetiver::vetiver_write_plumber(board, "modelo_lm", file = "config_api.r")

callr::r_bg(
  function() {
    pr <- plumber::plumb("config_api.r")
    pr$run(port = 8080)
  }
)

# Preparando um Dockerfile
# (vetiver_write_plumber + vetiver_prepare_docker)
vetiver::vetiver_prepare_docker(board, "modelo_lm")

# Ou passo a passo:
vetiver::vetiver_write_plumber(board, "modelo_lm")
vetiver::vetiver_write_docker(modelo_vetiver)
