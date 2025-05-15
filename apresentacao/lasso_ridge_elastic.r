library(tidymodels)
library(tibble)
library(purrr)
library(ggplot2)
library(patchwork)
library(future)
library(probably)

rm(list = ls())

# Removendo possíveis conflitos de pacotes --------------------------------
tidymodels::tidymodels_prefer()

# Paralelizando o código em Linux, Unix e Windows ----------------------
future::plan(future::multisession)

# Função para gerar os dados ----------------------------------------------
gerando_dados <- function(n = 300L) {
  regressao <- function(i) {
    x <- rnorm(n = 5L)
    y <- 3 * x[1L] - 2 * x[2L] + x[3L] - 3 * x[4L] + x[5L] + rnorm(1L, 0, 0.5)
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

# Fixando a semente para reprodutibilidade -----------------------------
set.seed(123)
dados <- gerando_dados(n = 500L)

# Divisão inicial da base -------------------------------------------------
dados_hold_out <- initial_split(dados, prop = 0.7, strata = y)
treino <- training(dados_hold_out)
teste <- testing(dados_hold_out)

# Setando o modelo (set engine) -------------------------------------------
modelo_lm <-
  linear_reg(penalty = 0, mixture = 0) |>
  set_mode("regression") |>
  set_engine("glmnet")

modelo_ridge <-
  linear_reg(penalty = tune::tune("lambda"), mixture = 0) |>
  set_mode("regression") |>
  set_engine("glmnet")

modelo_lasso <-
  parsnip::linear_reg(penalty = tune::tune("lambda"), mixture = 1) |>
  set_mode("regression") |>
  parsnip::set_engine("glmnet")

modelo_elastic <-
  parsnip::linear_reg(
    penalty = tune::tune("lambda"),
    mixture = tune::tune("alpha")
  ) |>
  set_mode("regression") |>
  parsnip::set_engine("glmnet")

# Criando workflows -------------------------------------------------------
all_wf <-
  workflow_set(
    preproc = list(y ~ .), # Não estou colocando receita
    models = list(
      lm = modelo_lm,
      ridge = modelo_ridge,
      lasso = modelo_lasso,
      elastic = modelo_elastic
    ),
    cross = FALSE
  )

# Validação cruzada -------------------------------------------------------
cv <- rsample::vfold_cv(treino, v = 5L)

# Tunagem dos hiperparâmetros ---------------------------------------------
# A semente (seed = 0) faz com que dentro da validação cruzada para cada modelo
# a semente seja sempre a mesma.
tunagem <-
  all_wf |>
  workflow_map(
    seed = 0, # Garantindo as mesmas amostras para cada modelo
    verbose = TRUE,
    resamples = cv,
    grid = 50,
    metrics = yardstick::metric_set(
      rmse,
      rsq,
      mae
    )
  )

# Rank dos melhores modelos -----------------------------------------------
modelos_rank <- tunagem |>
  rank_results()

# Visualizando os resultados na tunagem -------------------------------
# utilizando a EQM. Não é a avaliação final
# do modelo.
autoplot(tunagem, metric = "rmse") +
  aes(color = wflow_id)

# Extrair melhores configurações de hiperparâmetros ----------------------
melhores_configs <- list(
  ridge = tunagem |>
    extract_workflow_set_result("formula_ridge") |>
    select_best(metric = "rmse"),
  lasso = tunagem |>
    extract_workflow_set_result("formula_lasso") |>
    select_best(metric = "rmse"),
  elastic = tunagem |>
    extract_workflow_set_result("formula_elastic") |>
    select_best(metric = "rmse")
)

# Extraindo os melhores workflows e finalizando os modelos ------------
melhores_workflows <- list(
  ridge = tunagem |>
    extract_workflow("formula_ridge") |>
    finalize_workflow(melhores_configs$ridge),
  lasso = tunagem |>
    extract_workflow("formula_lasso") |>
    finalize_workflow(melhores_configs$lasso),
  elastic = tunagem |>
    extract_workflow("formula_elastic") |>
    finalize_workflow(melhores_configs$elastic)
)

# Último ajuste e avaliação final ------------------------------------------
resultados_teste <- map(
  melhores_workflows,
  ~ last_fit(.x, split = dados_hold_out) |>
    collect_metrics() |>
    filter(.metric == "rmse") |>
    pluck(3)
)

# Gerando tabela comparativa -----------------------------------------------
risco_preditivo <- tibble::tibble(
  modelo = names(resultados_teste),
  EQM = unlist(resultados_teste)
)

print(risco_preditivo)

# Modelo final -------------------------------------------------------------
modelo_final <-
  melhores_workflows$elastic |>
  fit(data = treino)

previsoes <- augment(modelo_final, new_data = teste)

# Visualizando as previsões ---------------------------------------------------
previsoes |>
  ggplot(aes(x = y, y = .pred)) +
  geom_point() +
  geom_smooth(formula = y ~ x, method = "lm", se = FALSE) +
  labs(
    title = "Previsões do modelo Elastic Net",
    x = "y",
    y = "Valores previstos"
  )

# Extrair importância das variáveis para o modelo final
var_imp <- modelo_final |>
  extract_fit_parsnip() |>
  vip::vi()

ggplot(var_imp, aes(x = Importance, y = reorder(Variable, Importance))) +
  geom_col(fill = "steelblue") +
  labs(title = "Importância das Variáveis", y = "Variável")
