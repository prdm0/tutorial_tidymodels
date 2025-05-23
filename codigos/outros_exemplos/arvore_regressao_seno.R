library(ggplot2)
library(tibble)
library(rpart)

random_y <- function(n = 250L, sigma = 0.1){
  x <- runif(n = n, min = 0, max = 10)
  tibble(x = x, y = rnorm(n = n, mean = sin(x), sd = sigma))
}

set.seed(0)

arvore <- function(dados, complexidade = 0.5, graph = TRUE, ...){
  
  dados <- random_y(...)
  
  arvore <- rpart::rpart(formula = y ~ ., data = dados)
  arvore <- rpart::prune(arvore, cp = complexidade) # Realizando poda
  
  dados$y_chapeu <- predict(arvore, newdata = dados)
  
  # Plotando x versus y -----------------------------------------------------
  dados |> 
    ggplot(aes(x, y)) + 
    geom_point() + 
    geom_line(aes(x, y_chapeu), linewidth = 1.5, col = "red") +
    labs(
      title = "Árvore de regressão",
      subtitle = glue::glue("Parâmetro de coplexidade = {complexidade}")
    )
}

arvore(complexidade = 0.2)




