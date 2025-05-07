library(tidymodels)
library(tibble)
library(purrr)
library(ggplot2)
library(patchwork)

# Removendo possíveis conflitos de pacotes --------------------------------
tidymodels::tidymodels_prefer()

# Função para gerar os dados ----------------------------------------------
gerando_dados <- function(n = 300L){
  regressao <- function(i){
    x <- rnorm(n = 5L)
    y <- 3*x[1L] - 2*x[2L] + x[3L] - 3*x[4L] + x[5L] + rnorm(1L, 0, 0.5)
    tibble(
      y = y,
      x1 = x[1L],
      x2 = x[2L],
      x3 = x[3L],
      x4 = x[4L],
      x5 = x[5L]
    )
  }
  dados <- purrr::map(.x = 1L:n, .f = regressao) |> 
    purrr::list_rbind()
  
  parte_esparsa <- matrix(0, n, 15)
  
  dados <- cbind(dados, parte_esparsa)
  colnames(dados) <- c("y", paste0("x", 2L:ncol(dados)))
  as_tibble(dados)
}

dados <- gerando_dados(n = 500)

# Divisão inicial da base -------------------------------------------------
hod_out <- initial_split(dados, prop = 0.7)
treinamento <- training(hod_out)
teste <- testing(hod_out)

# Setando o modelo (set engine) -------------------------------------------
modelo_eqm <- 
  linear_reg(penalty = 0, mixture = 0) |> 
  set_mode("regression") |> 
  set_engine("glmnet")
  
modelo_ridge <- 
  linear_reg(penalty = tune::tune(), mixture = 0) |> 
  set_mode("regression") |> 
  set_engine("glmnet")

modelo_lasso <- 
  parsnip::linear_reg(penalty = tune::tune(), mixture = 1) |> 
  set_mode("regression") |> 
  parsnip::set_engine("glmnet")
  
modelo_elastic <- 
  parsnip::linear_reg(penalty = tune::tune(), mixture = tune::tune()) |> 
  set_mode("regression") |> 
  parsnip::set_engine("glmnet")

# Criando workflows -------------------------------------------------------
all_wf <- 
  workflow_set(
    preproc = list(y ~ . ),
    models = list(eqm = modelo_eqm, ridge = modelo_ridge, lasso = modelo_lasso, elastic = modelo_elastic)
  )

# Validação cruzada -------------------------------------------------------
set.seed(0)
cv <- rsample::vfold_cv(treinamento, v = 5L)

# Setando a métrica -------------------------------------------------------
metrica <- yardstick::metric_set(rmse)

# Tunagem dos hiperparâmetros ---------------------------------------------
# A semente (seed = 0) faz com que dentro da validação cruzada para cada modelo
# a semente seja sempre a mesma.
tunagem <- 
  all_wf |> 
  workflow_map(
    seed = 0, 
    verbose = TRUE,
    resamples = cv,
    grid = 50,
    metrics = metrica
  )

# Rank dos melhores modelos -----------------------------------------------
modelos_rank <- tunagem |> rank_results()

melhor_eqm <- 
  tunagem |> 
  extract_workflow_set_result("formula_eqm") |> 
  select_best("rmse")

melhor_ridge <- 
  tunagem |> 
  extract_workflow_set_result("formula_ridge") |> 
  select_best("rmse")

melhor_lasso <- 
  tunagem |> 
  extract_workflow_set_result("formula_lasso") |> 
  select_best("rmse")

melhor_elastic <- 
  tunagem |> 
  extract_workflow_set_result("formula_elastic") |> 
  select_best("rmse")

finalizando_eqm <- 
  tunagem |> 
  extract_workflow("formula_eqm") |> 
  finalize_workflow(melhor_eqm) |> 
  last_fit(split = hod_out)

finalizando_ridge <- 
  tunagem |> 
  extract_workflow("formula_ridge") |> 
  finalize_workflow(melhor_ridge) |> 
  last_fit(split = hod_out)

finalizando_lasso <- 
  tunagem |> 
  extract_workflow("formula_lasso") |> 
  finalize_workflow(melhor_lasso) |> 
  last_fit(split = hod_out)

finalizando_elastic <- 
  tunagem |> 
  extract_workflow("formula_elastic") |> 
  finalize_workflow(melhor_elastic) |> 
  last_fit(split = hod_out)

# Visualizando as métricas
finalizando_eqm |> collect_metrics()
finalizando_ridge |> collect_metrics()
finalizando_lasso |> collect_metrics()
finalizando_elastic |> collect_metrics()