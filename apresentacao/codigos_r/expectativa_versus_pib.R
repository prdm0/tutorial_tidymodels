library(rsample)
library(yardstick)
library(tibble)
library(purrr)
library(ggplot2)
library(patchwork)

# Lendo dados
url <- "https://github.com/prdm0/dados/raw/main/dados_expectativa_renda.RData"
arquivo_temp <- tempfile()
download.file(url = url, destfile = arquivo_temp)
load(arquivo_temp)

dados <- 
  dados_expectativa_renda |> 
  dplyr::select(-CountryName) |> 
  dplyr::rename(y = LifeExpectancy, x = GDPercapita)
  
iteracoes <- function(tibble_data, grau) {
  x <- tibble_data$x
  iteracoes <- lapply(X = 2L:grau, FUN = function(i) x^i)
  
  result <- cbind(tibble_data, do.call(cbind, iteracoes))
  colnames(result)[(ncol(tibble_data) + 1):ncol(result)] <- paste0("x", 2L:grau)
  
  as_tibble(result)
}  

regressao_polinomial <- function(dados, grau = 1L) {
  if(grau >= 2L)
    dados <- iteracoes(dados, grau = grau)
  
  lm(formula = y ~ ., data = dados)
}

# Divisão dos dados
divisao_inicial <- rsample::initial_split(dados)
treinamento <- rsample::training(divisao_inicial)
teste <- rsample::testing(divisao_inicial) # Teste final

# v-folds cross-validation
validacao <- function(dados, grau = 1L, errado = FALSE, ...){
  
  # Todas as divisões da validacao cruzada
  cv <- rsample::vfold_cv(dados, ...)
  
  hiper <- function(i){
    treino <- rsample::analysis(cv$splits[[i]]) # Treinamento
    validacao <- rsample::assessment(cv$splits[[i]]) # Validacação
    ajuste <- regressao_polinomial(dados = treino, grau = grau)
    
    if(errado){
      df_treino <- iteracoes(treino, grau = grau)
      df_treino <- df_treino |> dplyr::mutate(y_chapeu = predict(ajuste, newdata = df_treino))
      yardstick::rmse(data = df_treino, truth = y, estimate = y_chapeu)$.estimate
    } else {
      df_validacao <- iteracoes(validacao, grau = grau)
      df_validacao <- df_validacao |> dplyr::mutate(y_chapeu = predict(ajuste, newdata = df_validacao))
      yardstick::rmse(data = df_validacao, truth = y, estimate = y_chapeu)$.estimate
    }
  }
  purrr::map_dbl(.x = seq_along(cv$splits), .f = hiper) |> 
    mean()
}

plot_avaliacao <- function(dados, errado = FALSE){
  # Testando iterativamente, vários valores de p:
  p <- seq(1L:11L)
  risco <- purrr::map_dbl(.x = p, .f = \(p) validacao(dados = dados, grau = p, errado = errado))
  df_risco <- tibble::tibble(p = p, risco = risco)
  
  # Plotando
  df_risco |> 
    ggplot(aes(x = p, y = risco, color = risco)) +
    geom_point(size = 5) +
    scale_x_continuous(breaks = p) +
    scale_y_continuous(breaks = p) +
    labs(
      title = "Valiando o risco estimado para diversos graus do polinômio",
      subtitle = "EQM no conjunto de validação"
    ) +
    theme(
      plot.title = element_text(size = 18, face = "bold"),
      plot.subtitle = element_text(size = 16),
      axis.text = element_text(size = 10), 
      axis.title = element_text(size = 14, face = "bold")
    )
}

# Avaliacão errada versus correta
set.seed(0)
grafico <- 
  plot_avaliacao(dados, errado = TRUE) + 
  plot_avaliacao(dados, errado = FALSE) +
  plot_annotation(tag_levels = c("A", "B"))

ggsave(grafico, file = "imgs/avaliacao_risco.png", device = "png", width = 50, height = 20, units = "cm", limitsize = F)

plot_bar <- function(grau){
  ruim <- validacao(dados, errado = TRUE, grau = grau)
  bom <- validacao(dados, errado = FALSE, grau = grau)
  df <- tibble::tibble(x = c("Errado", "Certo"), y = c(log(ruim), log(bom)))
  
  df |> 
    ggplot(aes(x = x, y = y)) +
    geom_bar(stat = "identity") +
    geom_text(aes(label = y), vjust = 0)
}
