library(tidymodels)
library(ggplot2)
library(vroom)
library(visdat)
library(future)
library(dplyr)
library(janitor)
library(iml)
library(patchwork)
library(pins)
library(vetiver)

# Resolvendo questões de ambiguidade de funções entre pacotes
tidymodels::tidymodels_prefer(quiet = TRUE)

# Definindo esquema de paralelização em todos os sistemas operacionais
# cores <- parallelly::availableCores(logical = FALSE)
# future::plan(future::multicore, workers = cores)

# Lendo dados
dados <- vroom::vroom("teresina.csv", show_col_types = FALSE) |>
  janitor::clean_names()

# Olhando rapidamente para os dados
visdat::vis_dat(dados)

# Melhorando os nomes das colunas
dados <- dados |>
  janitor::clean_names()

dados <- dados |>
  dplyr::select(
    -id,
    -endereco,
    -url,
    -bairro,
    -iptu,
    -condominio,
    -comercio
  )

dados |>
  dplyr::count(tipo)

dados <-
  dados |>
  dplyr::mutate(
    tipo = dplyr::case_when(
      tipo == "apartamentos" ~ "apartamento",
      tipo == "casas" ~ "casa",
      tipo == "casas_de_condominio" ~ "casa",
      tipo == "casas_de_vila" ~ "casa",
      tipo == "flat" ~ "apartamento",
      TRUE ~ tipo
    )
  ) |>
  dplyr::mutate(valor = log10(valor))

dados <- dados |> filter(tipo %in% c("apartamento", "casa"))

dados |>
  dplyr::count(tipo)

set.seed(123)
# Dividindo os dados em treino e teste
dados_split <- initial_split(
  dados,
  prop = 0.8,
  strata = valor
)
treino <- training(dados_split)
teste <- testing(dados_split)

# Especificando o modelo
modelo <- rand_forest(mtry = tune(), min_n = tune()) |>
  set_engine("ranger") |>
  set_mode("regression")

# Realizando a receita de pré-processamento
receita <- recipe(valor ~ ., data = treino) |>
  recipes::step_log(
    all_numeric_predictors(),
    -latitude,
    -longitude,
    offset = 1L,
    base = 10
  ) |>
  recipes::step_impute_knn(
    all_numeric_predictors(),
    impute_with = imp_vars(area, banheiro, quarto, tipo)
  ) |>
  recipes::step_normalize(all_numeric_predictors()) |>
  recipes::step_corr(all_numeric_predictors()) |>
  recipes::step_dummy(all_nominal_predictors()) |>
  recipes::step_mutate(across(where(is.logical), .fns = as.numeric)) |>
  recipes::step_nzv(all_predictors())

dados_prep <- prep(receita) |> bake(new_data = NULL)

# Criando o conjunto de validação (5-fold cross-validation)
cv <- vfold_cv(
  treino,
  v = 5,
  strata = valor
)

# Definindo o workflow (modelo + receita)
wf <- workflow() |>
  add_model(modelo) |>
  add_recipe(receita)

tunagem <-
  tune_grid(
    wf,
    resamples = cv,
    grid = 5,
    metrics = metric_set(yardstick::rmse, yardstick::rsq),
    control = control_grid(verbose = TRUE, parallel_over = "everything")
  )

# Ordenando os pseudo-r2 em ordem decrescente. Você poderia
# considerar o rmse (eu até prefiro).
tunagem |>
  collect_metrics(summarize = TRUE) |>
  dplyr::filter(.metric == "rsq") |>
  dplyr::arrange(desc(mean))

# Melhor modelo
melhor_hiperparametro <- tunagem |>
  select_best(metric = "rsq")

# Finalizando o workflow, retreinando com todos os dados
# do conjunto de treino e avaliando nos dados independentes
# de teste.
wf_final <- wf |>
  finalize_workflow(melhor_hiperparametro) |>
  last_fit(split = dados_split)

# Avaliação imparcial no conjunto de teste
wf_final |>
  collect_metrics(summarize = TRUE)

# Plotando as real vs previsões
wf_final |>
  collect_predictions() |>
  ggplot(aes(x = valor, y = .pred)) +
  geom_point() +
  geom_smooth(method = "lm", color = "blue", linewidth = 1.7) +
  theme_minimal() +
  labs(
    title = "Predições vs Valores",
    x = "Valores",
    y = "Predições"
  )

d <- prep(receita) |> bake(new_data = teste[sample(500L), ])
x <- dplyr::select(d, -valor)

# Realizando análise das variáveis ---------------------------------------
preditor <- iml::Predictor$new(
  extract_fit_parsnip(wf_final),
  data = x,
  y = d$valor
)

efeito <- iml::FeatureEffects$new(preditor, method = "pdp+ice")
p1 <- efeito$plot()

imp <- iml::FeatureImp$new(preditor, loss = "rmse")
p2 <- imp$plot()

# p1 / p2

# ! Criando uma api vetiver
modelo_vetiver <-
  vetiver::vetiver_model(
    extract_workflow(wf_final),
    "modelo_teresina"
  )

# Criando o board para poder pinar o modelo
board <- pins::board_folder(
  path = "modelo_teresina"
)

# ! Pinando o modelo
vetiver::vetiver_pin_write(
  board = board,
  vetiver_model = modelo_vetiver
)

#* Criando uma API com o vetiver
pr <- vetiver::vetiver_api(plumber::pr(), modelo_vetiver)
vetiver::vetiver_api(plumber::pr(), modelo_vetiver)$run(port = 8080)

# Gerando o arquivo plumber para rodar a API

vetiver::vetiver_write_plumber(
  board = board,
  name = "modelo_teresina",
  file = "api.r"
)

# Rodando o arquivo api.r
api <- callr::r_bg(
  function() {
    plumber::plumb("api.r")$run(port = 8000)
  }
)

# Preparando um arquivo Dockerfile
vetiver::vetiver_prepare_docker(
  board = board,
  name = "modelo_teresina",
  version = NULL,
  docker_args = list(port = 8000)
)
