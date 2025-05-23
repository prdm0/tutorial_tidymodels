library(rpart)
library(rpart.plot)

dados <- readr::read_csv(file = "dados/winequality-red.csv")

arvore <- dados |> 
  rpart::rpart(formula = quality ~ ., data = _) 

# Escolhendo o melhor grau de compexidade. É o o que possui menor erro:
melhor_grau <- arvore$cptable[nrow(arvore$cptable),][1L]

arvore_podada <- rpart::prune(tree = arvore, cp = 0.01)


rpart.plot::rpart.plot(arvore)
rpart.plot::rpart.plot(arvore_podada)

#