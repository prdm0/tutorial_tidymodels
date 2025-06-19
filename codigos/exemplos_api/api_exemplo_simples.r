library(plumber)

modelo <- lm(mpg ~ wt + hp, data = mtcars)

#* Gerando um histograma a cada requisição
#* @get /histograma_get
#* @serializer png
histograma_get <- function() {
  hist(
    rnorm(1000),
    main = "Histograma de Números Aleatórios",
    xlab = "Valor", ylab = "Frequência"
  )
}

#* Gerando um histograma a de "n" observações
#* @param n Número de observações
#* @param sd Desvio padrão
#* @get /histograma_get_n
#* @serializer tiff
histograma_get_n <- function(n = 1000, sd = 1) {
  n <- as.numeric(n)
  sd <- as.numeric(sd)

  hist(
    rnorm(n = n, sd = sd),
    main = paste("Histograma de", n, "Números Aleatórios"),
    xlab = "Valor", ylab = "Frequência"
  )
}

#* Predicao do modelo de regressão linear
#* @param wt Peso do carro
#* @param hp Potência do motor
#* @get /lm
lm <- function(wt, hp) {
  wt <- as.numeric(wt)
  hp <- as.numeric(hp)

  if (is.na(wt) || is.na(hp)) {
    return(list(error = "wt e hp devem ser números"))
  }
  pred <- predict(modelo, newdata = data.frame(wt = wt, hp = hp))
  return(list(prediction = pred))
}

#* Retornando uma lista
#* @get /lista
lista <- function() {
  return(list(
    lista = list("Joao", "Maria"),
    idade = 30,
    profissao = "Engenheiro"
  ))
}
