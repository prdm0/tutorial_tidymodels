library(tidymodels)
library(glue)
library(dplyr)
library(ggplot2)
library(patchwork)

tidymodels::tidymodels_prefer()

# Lendo dados
url <- "https://github.com/prdm0/dados/raw/main/dados_expectativa_renda.RData"
arquivo_temp <- tempfile()
download.file(url = url, destfile = arquivo_temp)
load(arquivo_temp)

dados <- 
  dados_expectativa_renda |> 
  dplyr::select(-CountryName) |> 
  dplyr::rename(y = LifeExpectancy, x = GDPercapita)

knn_exp_pip <- function(dados, k = 1L){
  # Criando receita
  receita <- recipe(y ~ x, data = dados)
  
  # Definindo o modelo
  modelo_knn <- nearest_neighbor(neighbors = k) |> 
    set_mode("regression") |> 
    set_engine("kknn")
  
  # Workflow
  ajuste_final <- 
    workflow() |> 
    add_model(modelo_knn) |> 
    add_recipe(receita) |> 
    fit(data = dados)
  
  # Retornando previsoes
  y_chapeu <- predict(ajuste_final, new_data = dados)
  
  dados <- 
    dados |> 
    mutate(y_chapeu = y_chapeu$.pred)
  
  dados |> 
    ggplot() +
    geom_point(aes(x = x, y = y), size = 3) +
    geom_line(aes(x = x, y = y_chapeu), col = "red", alpha = 0.6, size = 2) +
    labs(title = "k-nearest neighbours", subtitle = glue("k = {k}")) +
    theme(
      title = element_text(face = "bold")
    )
}

p1 <- knn_exp_pip(dados, k = 1L)
p2 <- knn_exp_pip(dados, k = 7L)
p3 <- knn_exp_pip(dados, k = 10L)
p4 <- knn_exp_pip(dados, k = 200L)

p <- p1 + p2 + p3 + p4 + plot_annotation(tag_levels = "A")

ggsave(p, file = "imgs/knn_plot.png", width = 50, height = 30, units = "cm")