library(tibble)
library(rpart)
library(ranger)
library(ggplot2)
library(purrr)
library(rsample)

random_y <- function(n = 250L, sigma = 0.1){
  x <- runif(n = n, min = 0, max = 10)
  tibble(x = x, y = rnorm(n = n, mean = sin(x), sd = sigma))
}

mc <- function(m = 10L, n = 10, sigma = 0.1, modelo = "floresta"){

  cenarios <- function(n, sigma){
    dados <- random_y(n = n, sigma = sigma)
    if(modelo == "bagging"){
      dados <- 
        dados[rsample::bootstraps(dados, times = 1L) |> 
        _$splits[[1L]]$in_id,]
    }
    
    # Modelos
    arvore <- 
      rpart::rpart(formula = y ~ ., data = dados) |> 
      predict(new.data = dados)
    
    floresta <- 
      ranger::ranger(formula = y ~ ., data = dados) |> 
      predict(data = dados, type = "response") |> 
      _$predictions
    
    dados$y_arvore <- arvore
    dados$y_floresta <- floresta
    
    dados
  }
  
  step_arvore <- function(i){
    resultados <- cenarios(n = n, sigma)
    tibble(
      x = resultados$x,
      y = resultados$y,
      arvore = resultados$y_arvore,
      floresta = resultados$y_floresta
    )
  }
  
  resultados_mc <- purrr::map(.x = 1L:m, .f = step_arvore)
  resultados_mc <- purrr::list_rbind(resultados_mc)
  resultados_mc$modelos <- rep(1L:(nrow(resultados_mc)/n), each = n) 

  # Plotando
  
  if(modelo == "floresta"){
    resultados_mc |>
      ggplot(aes(x = x, y = y)) +
      geom_line(aes(x = x, y = floresta, color = modelos)) +
      geom_smooth(se = FALSE, color = "red")
  } else if(modelo == "bagging") {
    resultados_mc |>
      ggplot(aes(x = x, y = y)) +
      geom_line(aes(x = x, y = arvore, color = modelos)) +
      geom_smooth(se = FALSE, color = "red")
  }
}


