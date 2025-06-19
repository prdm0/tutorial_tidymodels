library(pins)
library(plumber)
library(rapidoc)
library(vetiver)
library(jsonlite)

b <- board_folder(path = "modelo_teresina")
v <- vetiver_pin_read(b, "modelo_teresina")

predict_real <- function(req) {
    new_data <- jsonlite::fromJSON(req$postBody)
    preds <- predict(v, new_data)
    preds$.real <- 10^preds$.pred
    preds
}

soma_get <- function(a, b) {
    list(resultado = a + b)
}

soma_post <- function(req) {
    entrada <- jsonlite::fromJSON(req$postBody)
    a <- entrada$a
    b <- entrada$b

    list(resultado = a + b)
}

# Podemos usar anotações @get e @post mesmo quando temos @plumber

#* Dizendo olá
#* @get /ola_get
ola_get <- function() {
    list(message = "Olá, mundo!")
}

#* Dizendo olá
#* @param name Nome da pessoa
#* @post /ola_post
ola_post <- function(name = "mundo") {
    list(message = paste("Olá,", name, "!"))
}

#* @plumber
function(pr) {
    pr <- vetiver_api(pr, v)
    # pr$handle("POST", "/real", predict_real(v))
    # pr$handle("GET", "/soma_get", soma_get())
    # pr$handle("POST", "/soma_post", soma_post())
    pr |>
        pr_post("/real", predict_real) |>
        pr_get("/soma_get", soma_get) |>
        pr_post("/soma_post", soma_post)
}

# Fazendo requisicoes em httr2
# GET:
# request("http://localhost:8080/soma_get") |>
# req_url_query(a = 1, b = 2) |>
# req_perform() |>
# resp_body_json()

# POST:
# request("http://localhost:8080/soma_post") |>
# req_body_json(list(a = 1, b = 6)) |>
# req_perform() |>
# resp_body_json()

# curl GET
# curl -X GET "http://localhost:8080/soma_get?a=1&b=2"

# curl POST
# curl -X 'POST' \
#   'http://localhost:8080/soma_post' \
#   -H 'accept: application/json' \
#   -H 'Content-Type: application/json' \
#   -d '{"a": 3, "b": 6}'
