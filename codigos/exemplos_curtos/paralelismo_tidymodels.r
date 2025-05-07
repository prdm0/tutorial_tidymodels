library(tidymodels)
library(doFuture)

# ! Removendo problemas de compatibilidade
tidymodels::tidymodels_prefer()

# Todo: Todos os sistemas
# Todo: Paralelizando o código. Aqui teremos paralelização em todos os sistemas
cores <- parallelly::availableCores(logical = FALSE) # * Detectando o número de cores físicos

# ? Alternativamente poderíamos criar um clustre FORK parallel::makeForkCluster(cores)
cl <- parallel::makePSOCKcluster(cores) # * Criando um cluster PSOCK multiplataforma (Linux, Windows e Mac)
doParallel::registerDoParallel(cl) # * Registrando o cluster para uso com o pacote doParallel

# A tunagem viria aqui tune_grid()

foreach::registerDoSEQ() # * Desregistrando o cluster para evitar problemas de paralelização em outros códigos
parallel::stopCluster(cl)

# Todo: Paralelizando em Linux e Mac de forma eficiente
cores <- parallelly::availableCores(logical = FALSE) # * Detectando o número de cores físicos
#doFuture::registerDoFuture() # * Registrando o backend doFuture para paralelização
plan(future::multicore, workers = cores) # * Criando um plano de paralelização com o número de cores detectados
# A tunagem viria aqui tune_grid()
plan(future::sequential)
