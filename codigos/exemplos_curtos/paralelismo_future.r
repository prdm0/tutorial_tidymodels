library(future)
library(tictoc)

# * Matando dodos os processos de R: sudo pkill R

f <- function() {
  Sys.sleep(2)
  return(TRUE)
  #sum(rnorm(2e7))
}

n_sim <- 100L

future::plan(future::multicore) # Ou multicore se estiver no Linux/Mac

# Usando um funcional
tic()
# Crie todos os futuros de uma vez
futures <- lapply(1L:n_sim, \(i) future(f()))

# Espere por todos os resultados apenas uma vez
resultados <- value(futures)
toc()

# # Poderia ser um loop for
# resultados <- vector("list", n_sim)

# for (i in 1L:n_sim) {
#   resultados[[i]] <- future(f())
# }

# resultados <- value(resultados)

#future::plan(future::sequential)
