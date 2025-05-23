library(xml2)
library(httr)
library(stringr)

numero_pacotes_r <- httr::GET("https://cloud.r-project.org/web/packages/index.html") |> 
  xml2::read_html() |> 
  xml2::xml_find_all("//p[1]") |> 
  xml2::xml_text() |> 
  stringr::str_extract(pattern = "[0-9]+")