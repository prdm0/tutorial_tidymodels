library(ggplot2)
library(tibble)
library(ggplot2)
library(patchwork)

# Função de regressão verdadeira. Na prática é desconhecida.
regressao_verdadeira <- function(x)
  45 * tanh(x/1.9 - 7) + 57

observacoes_regressao_real <- function(n, desvio_padrao = 0.2) {
  # Permitindo que o mesmo x possa ter dois pontos de y, como ocorre na 
  # pratica
  seq_x <- sample(seq(0, 17.5, length.out = n), size = n, replace = TRUE)
  
  step <- function(x)
    regressao_verdadeira(x) + rnorm(n = 1L, mean = 0, sd = desvio_padrao)
  
  tibble::tibble(y = purrr::map_vec(.x = seq_x, .f = step), x = seq_x)
}

# Usaremos uma regressão polinomial para tentar ajustar à regressão -------
regressao_polinomial <- function(n = 30L, desvio_padrao = 4, grau = 1L) {
  
  dados <- observacoes_regressao_real(n = n, desvio_padrao = desvio_padrao)
    
  iteracoes <- function(tibble_data, grau) {
      x <- tibble_data$x
      iteracoes <- lapply(X = 2L:grau, FUN = function(i) x^i)
      
      result <- cbind(tibble_data, do.call(cbind, iteracoes))
      colnames(result)[(ncol(tibble_data) + 1):ncol(result)] <- paste0("x", 2L:grau)
      
      as_tibble(result)
  }  
  
  if(grau >= 2L)
    dados <- iteracoes(dados, grau = grau)
  
  ajuste <- lm(formula = y ~ ., data = dados)
  dados$y_chapeu <- predict(ajuste, new.data = dados)
  
  dados |> 
    dplyr::relocate(y_chapeu, .before = x)
}

plotando <- function(dados){
  dados |>  
    ggplot(aes(x = x, y = y_chapeu)) +
    geom_point()
}

mc_ajustes <- function(mc = 100L, n = 50L, desvio_padrao = 5, grau = 1L){

  p <- 
    ggplot(data = NULL) +
      coord_cartesian(xlim = c(0, 17.5), ylim = c(0, 110)) +      
      ylab("Valores estimados")
  
  df <- NULL
  for(i in 1L:mc){
    df <- regressao_polinomial(n = n, desvio_padrao = desvio_padrao, grau = grau)
    p <- p + geom_line(data = df, aes(x = x, y = y_chapeu))
  }
  p + 
    stat_function(fun = regressao_verdadeira, col = "red", size= 1.4) +
    labs(
      title = "Regressão Polinomial",
      subtitle = paste("Grau: ", grau)
    ) +
    theme(
      plot.title = element_text(face = "bold"),
      axis.title = element_text(face = "bold")
    )
}

set.seed(0)
p1 <- mc_ajustes(grau = 1, n = 100, desvio_padrao = 10)
p2 <- mc_ajustes(grau = 7, n = 100, desvio_padrao = 10)
p3 <- mc_ajustes(grau = 70, n = 100, desvio_padrao = 10)
p4 <- mc_ajustes(grau = 200, n = 100, desvio_padrao = 10)

p <- ((p1 | p2) / (p3 | p4)) + plot_annotation(tag_levels = "A")

ggsave(p, file = "imgs/vies_variancia.png", device = "png", width = 60, height = 40, units = "cm")