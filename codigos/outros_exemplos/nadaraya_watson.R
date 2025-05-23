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

nadaraya_watson_exp_pip <- function(dados, h = 1, ...){
  # Criando receita
  receita <- 
    recipe(y ~ x, data = dados) |> 
    step_normalize()
  
  # Definindo o modelo
  modelo_knn <- nearest_neighbor(dist_power = h, ...) |> 
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
    labs(title = "Nadaraya-Watson", subtitle = glue("h = {h}")) +
    theme(
      title = element_text(face = "bold")
    )
}

p1 <- nadaraya_watson_exp_pip(dados, h = 1, weight_func = "gaussian")
p2 <- nadaraya_watson_exp_pip(dados, h = 1000, weight_func = "gaussian")

p <- p1 + p2 + plot_annotation(tag_levels = "A")

ggsave(p, file = "imgs/nadaraya_watson.png", width = 30, height = 15, units = "cm")