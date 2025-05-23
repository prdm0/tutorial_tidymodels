library(tidymodels)
library(dplyr)
library(ggplot2)
library(patchwork)

# Resolvendo eventuais conflitos entre tidymodels e outros pacotes eventualmente
# carregados:
tidymodels::tidymodels_prefer()

# Lendo a base de dados:
url <- "https://github.com/prdm0/dados/raw/main/dados_expectativa_renda.RData"
arquivo_temp <- tempfile()
download.file(url = url, destfile = arquivo_temp)
load(arquivo_temp)

dados_expectativa_renda <-
  dados_expectativa_renda |>
  dplyr::select(-CountryName)

# Setando uma semente
set.seed(0)

# Divisão da base de dados ------------------------------------------------
# Divisão inicial (treino e teste)
splits <- 
  rsample::initial_split(
    dados_expectativa_renda,
    strata = "LifeExpectancy", 
    prop = 0.8 
  )

# O conjunto de dados de treinamento será utilizado para ajustar/treinar o
# modelo:
treinamento <- rsample::training(splits)

# O conjunto de teste será utilizado apenas no fim, para avaliar o desempenho
# preditivo final do modelo:
teste <- rsample::testing(splits) 

# Criando uma receita para os dados ---------------------------------------

# Poderia ter passado o conjunto treinamento ou posso passar o conjunto "splits".
# O comando recipes já entende que deverá utilizar o conjunto de treinamento.
receita <- 
  recipes::recipe(formula = LifeExpectancy ~ ., data = treinamento) |> 
  step_YeoJohnson(all_predictors()) |> # Ajuda na normalização dos dados. Pode ser bom!
  step_normalize(all_predictors()) # Normalizando variáveis numéricas.

# Construindo modelo kNN --------------------------------------------------
modelo_knn <- 
  parsnip::nearest_neighbor(neighbors = tune()) |> 
  parsnip::set_mode("regression") |> 
  parsnip::set_engine("kknn")

# Construindo um workflow (pipeline) --------------------------------------
wf_knn <-
  workflows::workflow() |>
  workflows::add_recipe(receita) |>
  workflows::add_model(modelo_knn)

# Cross-validation --------------------------------------------------------
cv <- 
  treinamento |> 
  rsample::vfold_cv(v = 10L, strata = "LifeExpectancy")

# Busca do hiperparâmetro k -----------------------------------------------
metrica <- metric_set(rmse)

# Extraindo e atualizando range do parâmetro ------------------------------
update_parametros <-
  wf_knn |> 
  extract_parameter_set_dials() |>
  update("neighbors" = neighbors(c(1, 50)))

# Tunagem -----------------------------------------------------------------
meu_grid <- dials::grid_max_entropy(update_parametros, size = 60)

tunagem <-
  tune::tune_grid(
    wf_knn,
    resamples = cv,
    grid = meu_grid,
    metrics = metrica,
    control = control_grid(save_pred = TRUE, verbose = TRUE)
  )

p_hiper <- autoplot(tunagem) +
  labs(title = "KNN - Seleção do número k (vizinhos)", subtitle = "Sintonização do hiperparâmetro (valor de k)") +
  theme(
    title = element_text(face = "bold")
  )

# Atualizando workflow ----------------------------------------------------
wf_knn <- 
  wf_knn |> 
  finalize_workflow(select_best(tunagem))

# Ajustar o modelo ao conjunto de treinamento e avaliar no teste --------
ajuste_final <- last_fit(wf_knn, splits)

# Ajuste final com toda a base de dados -----------------------------------
modelo_final <- fit(wf_knn, data = dados_expectativa_renda)

# Visualizando as predições na base de treino
p_ajuste <- ajuste_final$.predictions[[1L]] |> 
  ggplot(aes(x = LifeExpectancy, y = .pred)) + 
  geom_point(size = 3, alpha = 0.7, col = "red") +
  labs(
    title = "Predições versus Real", 
    subtitle = "Usando apenas os dados de teste"
  ) +
  xlab("LifeExpectancy") + 
  xlab("LifeExpectancy predito") + 
  theme(
    title = element_text(face = "bold")
  )

# Unindo os dois plots
p <- p_hiper + p_ajuste + plot_annotation(tag_levels = "A")

# Salvando gráficos
ggsave(p, file = "imgs/plot_hiper_ajuste_tidymodels_knn.png", width = 30,
       height = 15, units = "cm")