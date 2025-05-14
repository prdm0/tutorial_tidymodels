library(tidymodels)
library(tibble)
library(dplyr) # Para a função mutate
library(future)
library(readr)

# Configurando o ambiente para paralelização
future::plan(future::multisession())

tidymodels::tidymodels_prefer(quiet = TRUE)

# Carregando dados referente a qualidade de vinhos
dados <- readr::read_csv("dados/winequality-red.csv")

set.seed(123)
dados_split <- initial_split(dados, prop = 0.8, strata = quality)
dados_treino <- training(dados_split)
dados_teste <- testing(dados_split)

# Verificando a estrutura dos dados (opcional)
# glimpse(dados)
modelo_lm <- linear_reg() |>
  set_engine("lm") |>
  set_mode("regression")

modelo_arvore <- decision_tree() |>
  set_engine("rpart") |>
  set_mode("regression")

receita_1 <- recipe(quality ~ ., data = dados_treino) |>
  step_YeoJohnson(all_numeric_predictors()) |>
  step_normalize(all_numeric_predictors()) |>
  step_zv(all_predictors()) |>
  step_corr(all_numeric_predictors(), threshold = 0.9)

receita_2 <- recipe(quality ~ ., data = dados_treino) |>
  step_pca(all_numeric_predictors(), threshold = 0.75) |>
  step_zv(all_predictors())

# Criando e gerenciando múltiplos workflows
# coss = TRUE indica que os workflows devem ser cruzados
wf_set <- workflow_set(
  preproc = list(
    receita_1 = receita_1,
    receita_2 = receita_2
  ),
  models = list(
    lm = modelo_lm,
    arvore = modelo_arvore
  ),
  cross = TRUE # Para criar combinações de receitas e modelos
)

# Usando a função fit_resamples para ajustar os modelos
# e calcular as métricas de desempenho.
# 5-fold cross-validation
cv <- vfold_cv(dados_treino, v = 5, strata = quality)

# Usando workflow_map para ajustar os modelos
wf_set <- wf_set |>
  workflow_map(
    "fit_resamples",
    resamples = cv,
    control = control_resamples(save_pred = TRUE, parallel_over = "everything"),
    metrics = metric_set(rmse, rsq, mae),
    verbose = TRUE
  )

collect_metrics(wf_set) |>
  filter(.metric == "rmse") |>
  arrange(desc(mean))

autoplot(wf_set)
