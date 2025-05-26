# Carregando bibliotecas
library(vetiver)
library(plumber)
library(callr)
library(pins)
library(mirai)

# Meu modelo bem simples
modelo <- lm(mpg ~ ., data = mtcars)

# Meu modelo vetiver
modelo_vetiver <-
  vetiver::vetiver_model(
    model = modelo,
    model_name = "lm_mtcars_v1"
  )

# Criando um quadro para pins
board <-
  pins::board_folder(
    "modelos",
    versioned = TRUE
  )

# Pinando o modelo com o vetiver
vetiver::vetiver_pin_write(board, modelo_vetiver)

# Criando e rodando a API rapidamente
# pr <- vetiver::vetiver_api(pumber::pr(), modelo_vetiver)
# pr$run(port = 8080)

# Criando um arquivo plumber
vetiver::vetiver_write_plumber(board, "lm_mtcars_v1.0", file = "api.r")

api <- callr::r_bg(
  function() {
    plumber::plumb("api.r")$run(port = 8080)
  }
)

# Matando a API
api$kill()

# api <- mirai(
#   {
#     plumber::plumb("api.r")$run(port = 8080)
#   }
# ) # Não funciona bem para esse propósito. Usar onde o future for útil.

endpoint <- vetiver::vetiver_endpoint("https://api-mtcars.koyeb.app/predict")

predict(endpoint, tibble::tibble(wt = 2.7))
