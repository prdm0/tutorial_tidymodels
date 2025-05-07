library(future)
library(tictoc)

one_step <- function() {
  Sys.sleep(10)
  return(TRUE)
}

plan(multicore)

value %<-%
  {
    one_step()
  }

cat("1 + 1 = ", 1 + 1, "\n")
cat("sum(value) = ", sum(value), "\n")
