library(pins)
library(plumber)
library(rapidoc)
library(vetiver)
library(jsonlite)

b <- board_folder(path = "modelo_teresina")
v <- vetiver_pin_read(b, "modelo_teresina")

predict_real <- function(v) {
    function(req) {
        new_data <- jsonlite::fromJSON(req$postBody)
        preds <- predict(v, new_data)
        preds$.real <- 10^preds$.pred
        preds
    }
}

soma <- function() {
    function(req) {
        valores <- jsonlite::fromJSON(req$postBody)
        a <- valores$a
        b <- valores$b
        list(resultado = a + b)
    }
}

histograma <- function() {
    function() {
        x <- rnorm(1000)
        hist(
            x,
            main = "Histograma de Números Aleatórios",
            xlab = "Valor",
            ylab = "Frequência"
        )
    }
}

#* @plumber
function(pr) {
    pr <- vetiver_api(pr, v)
    pr$handle("POST", "/real", predict_real(v))
    pr$handle("POST", "/soma", soma())
    pr$handle("GET", "/histograma", histograma())
    pr
}
