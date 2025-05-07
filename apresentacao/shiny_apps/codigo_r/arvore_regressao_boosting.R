library(rsample)
library(rpart)
library(purrr)
library(tibble)
library(ggplot2)
library(tidymodels)

tidymodels::tidymodels_prefer()

random_y <- function(n = 250L, sigma = 0.1){
  x <- runif(n = n, min = 0, max = 10)
  tibble(x = x, y = rnorm(n = n, mean = sin(x), sd = sigma))
}

dados <- random_y(n = 250L, sigma = 0.1)

# dados$r <- dados$y
# 
# boosting <- function(B = 1000L, depth = 4L, lambda = 0.01){
#   step <- function(g, b){
#     g_b <- ranger::ranger(r ~ x, data = dados, max.depth = depth)
#     g <- g + lambda * predict(object = g_b, data = dados) |> 
#       _$predictions
#     dados$r <- dados$y - g
#     g
#   }
#   purrr::reduce(.x = 1:B, .f = step, .init = 0)
# }
# dados$y_boosting <- boosting()
# 
# dados |> 
#   ggplot(aes(x = x, y = y)) +
#   geom_smooth(se = FALSE) +
#   geom_line(aes(x = x, y = y_boosting))

# Definindo o modelo ------------------------------------------------------


boosting <- function(n = 250L, sigma = 0.1, B = 1000L, depth = 4L, lambda = 0.01){
  
  dados <- random_y(n = n, sigma = sigma)
  
  modelo <- 
  parsnip::boost_tree(trees = B, tree_depth = depth, learn_rate = lambda) |> 
  parsnip::set_mode("regression") |> 
    parsnip::set_engine("xgboost")
  
  modelo_ajustado <- 
    parsnip::fit(object = modelo, formula = y ~ ., data = dados)
  
  dados$y_boosting <- predict(modelo_ajustado, new_data = dados)$.pred
  
  dados |>
    ggplot(aes(x = x, y = y)) +
    geom_smooth(se = FALSE) +
    geom_line(aes(x = x, y = y_boosting))
}


