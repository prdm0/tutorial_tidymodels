library(tidymodels)
library(probably)
library(parallel)
library(parallelly)
library(future)
library(doRNG)
library(ggplot2)

rm(list = ls(all = TRUE))

#Todo: Aqui iremos definir a paralelização de forma multiplataforma
cores <- parallelly::availableCores(logical = FALSE)
#cl <- parallel::makePSOCKcluster(cores) #* Criando um cluster PSOCK multiplataforma (Linux, Windows e Mac)
plan(multicore, workers = cores) #* Registrando o cluster para uso com o pacote doParallel

#! Resolvendo problemas de incompatibildiade
tidymodels::tidymodels_prefer()

# * Conjunto de dados
dados <- iris

doRNG::registerDoRNG(123) #* Registrando o gerador de números aleatórios para garantir reprodutibilidade

# * Realizando o Holdout (divisão dos dados em treino e teste)
dados_split <- rsample::initial_split(
  data = dados,
  prop = 3 / 4,
  strata = Species
)
train <- rsample::training(dados_split) #* Dados não-teste
test <- rsample::testing(dados_split) #* Dados de teste

# Creiando uma receita simples
receita <-
  train |>
  recipe(Species ~ ., data = _) |>
  step_normalize(all_numeric_predictors()) |>
  step_zv(all_numeric_predictors())

# Definindo o modelo random forest com a biblioteca ranger
modelo <-
  parsnip::rand_forest(mtry = tune("m"), trees = tune()) |>
  parsnip::set_engine("ranger") |>
  parsnip::set_mode("classification")

# Observando a tansformação (preparando a refeita)
receita |> prep() |> bake(new_data = train)

# Vamos definir as métricas para avaliação do modelo

metricas <- metric_set(
  # accuracy,
  # kap,
  # precision,
  # recall,
  # f_meas
  roc_auc
)

# Criando workflow
wf <-
  workflows::workflow() |>
  workflows::add_recipe(receita) |>
  workflows::add_model(modelo)

# Criando o conjunto de validação cruzada (k-fold)
set.seed(123)
dados_vfold <- rsample::vfold_cv(
  data = train,
  v = 5,
  strata = Species
) #* 5-fold cross-validation

# Tunando o modelo
metricas <- yardstick::metric_set(recall, accuracy)

tunagem <- tune::tune_grid(
  object = wf,
  resamples = dados_vfold,
  grid = 25L,
  metrics = metricas,
  control = tune::control_grid(
    verbose = TRUE,
    save_pred = TRUE, # Util para plotar os resultados
    save_workflow = TRUE
  )
)

## Explicitly close multisession workers by switching plan
plan(sequential)

## * Visualizando os resultados da tunagem

collect_predictions(tunagem) |> View()

collect_predictions(tunagem) |>
  conf_mat(truth = Species, estimate = .pred_class) |>
  autoplot(type = "heatmap") +
  labs(title = "Matriz de Confusão - Random Forest") +
  theme_minimal() +
  theme(legend.position = "bottom")

# Finalizando o workflow
wf_final <-
  tunagem |>
  select_best(metric = "accuracy") |>
  (\(.) finalize_workflow(wf, .))()

# Ultimo ajuste last_fit
final <-
  wf_final |>
  last_fit(
    split = dados_split,
    metrics = metricas
  )
collect_metrics(final)
