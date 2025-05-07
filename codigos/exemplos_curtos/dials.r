library(tidymodels)
library(tibble)
library(ggplot2)

#! Resolvendo problema de compabilidade
tidymodels::tidymodels_prefer()

# * Criando objeto da classe parameters
glmnet_set <- parameters(list(lambda = penalty(), alpha = mixture()))


# Testando algumas transformações úteis

valores <- c(0, 0.1, 0.5, 0.9, 1)
trans <- log2_trans()
trans$transform(valores)
trans$inverse(valores)

# Visualizando a transformação
plot(log2_trans(), xlim = c(0, 10))


# Criando um data frame de penalty()
penalty(trans = identity_trans()) |>
  parameters() |>
  grid_space_filling(size = 10) |>
  ggplot(aes(x = factor(seq_along(penalty)), y = penalty)) +
  geom_point()


grid_space_filling(penalty(), mixture(), size = 3)

# Criando e nomeando parameters
parameters(list(a = penalty(), b = mixture())) |> grid_space_filling(size = 5)

# Criando uma sequência de valores
penalty() |> value_seq(10)

penalty() |> range_get()

value_sample(penalty(), n = 10)
