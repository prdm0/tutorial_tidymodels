library(tidymodels)
library(tibble)
library(future)
library(broom)

# Resolvendo problemas de conflito de pacotes
tidymodels::tidymodels_prefer()

future::plan(multicore)

# Math: Y = 3 X_1 - 2 X_2 + X_3 - 3 X_4 + X_5 + \sum_{i=6}^{20} 0 X_i + \epsilon
# Math: \epsilon \sim N(0, 0.5)
# Math: X_i \sim N(0, 1)\,\, \forall i \in [1, 20]
# Função para gerar dados sintéticos do problema de regressão
gerar_dados <- function(n = 500, semente = 123) {
  set.seed(semente)

  # Gerar matriz X (500 x 20) com variáveis normais independentes
  x <- matrix(rnorm(n * 20, mean = 0, sd = 0.5), nrow = n, ncol = 20L)
  colnames(x) <- paste0("x", 1L:20L)

  # Coeficientes verdadeiros (beta)
  beta <- c(3, -2, 1, -3, 1, rep(0, 15L)) # X6 a X20 têm efeito zero

  # Gerar erro aleatório (epsilon)
  epsilon <- rnorm(n, mean = 0, sd = 0.5)

  # Calcular Y conforme o modelo
  y <- as.vector(x %*% beta + epsilon)
  dados <- tibble(y = y, as_tibble(x))

  return(dados)
}

# Gerando dados sintéticos
dados <- gerar_dados(n = 20000, semente = 123)

# Divisão dos dados entre treino e teste (holdout)
dados_split <- dados |>
  initial_split(prop = 0.8, strata = y)

treino <- training(dados_split)
teste <- testing(dados_split)

# Obtendo as amostras para validação cruzada
# 5-fold cross-validation
cv <- rsample::vfold_cv(treino, v = 10, strata = y)

# Definindo a receita

receita <- recipe(y ~ ., data = treino)

# Definindo o modelo lasso
modelo_lasso <- linear_reg(penalty = tune("lambda"), mixture = 1) |>
  set_engine("glmnet") |>
  set_mode("regression")

# Definindo o workflow
wf <- workflow() |>
  add_recipe(receita) |>
  add_model(modelo_lasso)

# Tunando o hiperparâmetro lambda
tunagem <- tune::tune_grid(
  wf,
  resamples = cv,
  grid = 50,
  metrics = metric_set(rmse),
  control = control_grid(save_pred = TRUE, parallel_over = "everything")
)

# Coletando as métricas
collect_metrics(tunagem)

# Show best
melhor_lambda <- select_best(tunagem, metric = "rmse")

# Finalizando o workflow com o melhor lambda
wf_final <- finalize_workflow(wf, melhor_lambda)

# Realizando o ultimo ajuste do modelo e avaliando no conjunto de teste
ajuste_final <- last_fit(wf_final, dados_split)

# Visualizando a métrica do modelo
collect_metrics(ajuste_final)

# Visualizando os resultados
ajuste_final |>
  collect_predictions() |>
  ggplot(aes(x = .pred, y = y)) +
  geom_point() +
  geom_abline(intercept = 0, color = "red") +
  labs(
    title = "Predições do modelo Lasso",
    x = "Predições",
    y = "Valores reais"
  ) +
  theme_minimal()

modelo_final <- extract_fit_parsnip(ajuste_final)

# Visualizando os coeficientes
tidy(modelo_final) |>
  filter(estimate == 0)

# Salvando o modelo
saveRDS(modelo_final, "modelo_lasso.rds")

# Carregando o modelo
modelo_lasso <- readRDS("modelo_lasso.rds")

# Realizando predições
predicoes <- predict(modelo_lasso, new_data = teste) # ou
augment(modelo_lasso, new_data = teste) # para incluir as predições no dataframe
