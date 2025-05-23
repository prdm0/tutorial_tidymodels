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
receita_knn <- 
  recipes::recipe(formula = LifeExpectancy ~ ., data = treinamento) |> 
  step_YeoJohnson(all_predictors()) |> # Ajuda na normalização dos dados. Pode ser bom!
  step_normalize(all_predictors()) # Normalizando variáveis numéricas.

receita_nadaraya <- receita_knn

# Construindo modelo kNN --------------------------------------------------
modelo_knn <- 
  parsnip::nearest_neighbor(neighbors = tune()) |> 
  parsnip::set_mode("regression") |> 
  parsnip::set_engine("kknn")

# Construindo modelo Nadaraya ---------------------------------------------
modelo_nadaraya <- 
  parsnip::nearest_neighbor(dist_power = tune(), neighbors = tune(),
                            weight_func = "gaussian") |> 
  parsnip::set_mode("regression") |> 
  parsnip::set_engine("kknn")

# Validação cruzada -------------------------------------------------------
set.seed(0)
cv <- rsample::vfold_cv(treinamento, v = 5L)

# Criando workflow conjunto -----------------------------------------------
all_wf <- 
  workflow_set(
    preproc = list(receita_knn, receita_nadaraya),
    models = list(modelo_knn = modelo_knn, modelo_nadaraya = modelo_nadaraya)
  )

# Tunando ambos os modelos ------------------------------------------------
tunagem <- 
  all_wf |> 
  workflow_map(
    seed = 0, 
    verbose = TRUE,
    resamples = cv,
    grid = 50,
    metrics = metric_set(rmse)
  )

# Selecionando o melhor de cada um dos modelos ----------------------------
melhor_knn <- 
  tunagem |> 
  extract_workflow_set_result("recipe_1_modelo_knn") |> 
  select_best("rmse")

melhor_nadaraya <- 
  tunagem |> 
  extract_workflow_set_result("recipe_1_modelo_nadaraya") |> 
  select_best("rmse")

# Avaliando o desempenho no conjunto de teste
teste_knn <- 
  tunagem |> 
  extract_workflow("recipe_1_modelo_knn") |> 
  finalize_workflow(melhor_knn) |> 
  last_fit(split = splits)

teste_nadaraya <- 
  tunagem |> 
  extract_workflow("recipe_1_modelo_nadaraya") |> 
  finalize_workflow(melhor_nadaraya) |> 
  last_fit(split = splits)

# Visualizando as métricas de cada um
collect_metrics(teste_knn)
collect_metrics(teste_nadaraya)

# Ajustando o modelo com todos os dados. Aqui escolhemos o Nadaraya-Watson
modelo_final <- 
  teste_nadaraya |> 
  extract_workflow("recipe_1_modelo_nadaraya") |> 
  fit(data = dados_expectativa_renda)

# Fazendo previsões com novos dados. Aqui usarei os mesmos dados
predict(modelo_final, new_data = dados_expectativa_renda)

# Salvando o modelo em um arquivo. Aqui estou supondo que salvei em
# "~/Downloads/modelo_final.rds":
# saveRDS(modelo_final, file = "~/Downloads/modelo_final.rds")

# Lendo um modelo salvo para depois fazer predições. Aqui estou supondo que 
# o modelo encontra-se salvo em "~/Downloads/modelo_final.rds":
# readRDS("~/Downloads/modelo_final.rds")


?purrr::accumulate()

1+1
