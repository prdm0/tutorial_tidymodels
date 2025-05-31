# ==============================================================================
# Aplicativo Shiny para Previsão de Preços de Imóveis - Teresina, PI
# ==============================================================================

# Carregar bibliotecas necessárias
library(shiny)
library(shinythemes) # Para temas visuais
library(httr2) # Para requisições HTTP
library(tidygeocoder) # Para geocodificação de endereços
library(dplyr) # Para manipulação de dados
library(DT) # Para tabelas interativas
library(jsonlite) # httr2 usa, mas é bom ter explícito

# --- Interface do Usuário (UI) ---
ui <- fluidPage(
  theme = shinytheme("cerulean"), # Escolha um tema, e.g., "cerulean", "flatly", "superhero"

  titlePanel(tagList(
    "🏡 Previsor de Preços de Imóveis - Teresina, PI",
    tags$p(tags$small(
      "Utilizando ",
      tags$a(
        href = "https://jessecambon.github.io/tidygeocoder/",
        target = "_blank",
        "tidygeocoder"
      ),
      " para conversão de endereço."
    ))
  )),

  sidebarLayout(
    sidebarPanel(
      width = 4,
      h4("🔌 Configuração da API"),
      textInput(
        "api_url",
        "URL da API de Previsão:",
        value = "https://modelo-teresina.fly.dev/predict"
      ),
      hr(),

      h4("📍 Localização e Características Principais"),
      textInput(
        "endereco",
        "Endereço Completo (Ex: Av. Nossa Senhora de Fatima, Teresina, Piaui / Rua Roland Jacob, Teresina, Piaui):",
        placeholder = "Digite o endereço aqui..."
      ),
      selectInput(
        "tipo",
        "🏢 Tipo de Imóvel:",
        choices = c("Apartamento", "Casa"),
        selected = "Apartamento"
      ),
      numericInput("area", "📐 Área Total (m²):", value = 100, min = 0),
      fluidRow(
        shiny::column(
          6,
          numericInput("quarto", "🛏️ Quartos:", value = 3, min = 0, step = 1)
        ),
        shiny::column(
          6,
          numericInput(
            "banheiro",
            "🚽 Banheiros:",
            value = 2,
            min = 0,
            step = 1
          )
        )
      ),
      numericInput(
        "vaga",
        "🚗 Vagas de Garagem:",
        value = 1,
        min = 0,
        step = 1
      ),
      hr(),

      h4("✨ Comodidades Adicionais"),
      fluidRow(
        shiny::column(
          6,
          checkboxInput("area_servico", "🧺 Área de Serviço", FALSE)
        ),
        shiny::column(
          6,
          checkboxInput("espaco_gourmet", "🍖 Espaço Gourmet", FALSE)
        )
      ),
      fluidRow(
        shiny::column(6, checkboxInput("piscina", "🏊 Piscina", FALSE)),
        shiny::column(6, checkboxInput("elevador", "🛗 Elevador", FALSE))
      ),
      fluidRow(
        shiny::column(
          6,
          checkboxInput("salao_de_festa", "🎉 Salão de Festa", FALSE)
        ),
        shiny::column(6, checkboxInput("academia", "🏋️ Academia", FALSE))
      ),
      fluidRow(
        shiny::column(6, checkboxInput("playground", "🤸 Playground", FALSE)),
        shiny::column(6, checkboxInput("quadra_de_esporte", "🏀 Quadra", FALSE))
      ),
      fluidRow(
        shiny::column(
          6,
          checkboxInput("portaria_24_horas", "🛡️ Portaria 24h", FALSE)
        ),
        shiny::column(
          6,
          checkboxInput("varanda_gourmet", "🌿 Varanda Gourmet", FALSE)
        )
      ),
      fluidRow(
        shiny::column(6, checkboxInput("sauna", "🧖 Sauna", FALSE)),
        shiny::column(6, checkboxInput("spa", "💆 Spa", FALSE))
      ),
      hr(),
      shiny::actionButton(
        "submit_btn",
        "Estimar Valor do Imóvel 💰",
        icon = icon("search-dollar"),
        class = "btn-primary btn-lg btn-block"
      )
    ),

    mainPanel(
      width = 8,
      h3("📊 Resultado da Estimativa"),
      # --- INÍCIO: Elemento UI para valor estimado destacado ---
      uiOutput("highlighted_prediction_output"),
      hr(), # Separador visual
      # --- FIM: Elemento UI ---
      DTOutput("resultTable")
    )
  )
)

# --- Lógica do Servidor (Server) ---
server <- function(input, output, session) {
  prediction_results_rv <- reactiveVal(NULL)
  # --- INÍCIO: ReactiveVal para o valor estimado destacado ---
  estimated_value_for_display_rv <- reactiveVal(NULL)
  # --- FIM: ReactiveVal ---

  observeEvent(input$submit_btn, {
    # --- Resetar valores em nova submissão ---
    estimated_value_for_display_rv(NULL)
    prediction_results_rv(NULL)

    showNotification(
      "Processando... buscando coordenadas e contatando API.",
      type = "message",
      duration = 5
    )

    if (input$endereco == "") {
      showNotification("Por favor, informe o endereço.", type = "warning")
      estimated_value_for_display_rv(
        tags$div(
          class = "alert alert-warning",
          style = "font-size: 18px; text-align: center;",
          "Entrada inválida: Por favor, informe o endereço."
        )
      )
      return()
    }
    if (is.na(input$area) || input$area <= 0) {
      showNotification(
        "Por favor, informe uma área válida (maior que zero).",
        type = "warning"
      )
      estimated_value_for_display_rv(
        tags$div(
          class = "alert alert-warning",
          style = "font-size: 18px; text-align: center;",
          "Entrada inválida: Por favor, informe uma área válida."
        )
      )
      return()
    }

    geocoded_address <- tryCatch(
      {
        tidygeocoder::geo(
          input$endereco,
          method = 'osm',
          quiet = TRUE,
          progress_bar = FALSE,
          limit = 1
        )
      },
      error = function(e) {
        showNotification(
          paste("Erro na geocodificação:", e$message),
          type = "error"
        )
        NULL
      }
    )

    if (
      is.null(geocoded_address) ||
        nrow(geocoded_address) == 0 ||
        is.na(geocoded_address$lat[1]) ||
        is.na(geocoded_address$long[1])
    ) {
      showNotification(
        "Endereço não encontrado ou falha ao obter coordenadas.",
        type = "error"
      )
      prediction_results_rv(data.frame(
        Erro = "Falha na geocodificação",
        Detalhes = "Não foi possível converter o endereço em coordenadas válidas."
      ))
      estimated_value_for_display_rv(
        tags$div(
          class = "alert alert-danger",
          style = "font-size: 18px; text-align: center;",
          "Não foi possível estimar o valor: Falha ao obter localização."
        )
      )
      return()
    }

    latitude_val <- geocoded_address$lat[1]
    longitude_val <- geocoded_address$long[1]

    payload <- list(list(
      area = as.numeric(input$area),
      quarto = as.integer(input$quarto),
      vaga = as.integer(input$vaga),
      banheiro = as.integer(input$banheiro),
      tipo = as.character(tolower(input$tipo)),
      latitude = latitude_val,
      longitude = longitude_val,
      area_servico = as.logical(input$area_servico),
      espaco_gourmet = as.logical(input$espaco_gourmet),
      piscina = as.logical(input$piscina),
      elevador = as.logical(input$elevador),
      salao_de_festa = as.logical(input$salao_de_festa),
      academia = as.logical(input$academia),
      playground = as.logical(input$playground),
      quadra_de_esporte = as.logical(input$quadra_de_esporte),
      portaria_24_horas = as.logical(input$portaria_24_horas),
      varanda_gourmet = as.logical(input$varanda_gourmet),
      sauna = as.logical(input$sauna),
      spa = as.logical(input$spa)
    ))

    api_url <- input$api_url
    if (api_url == "") {
      showNotification("URL da API não informada.", type = "error")
      estimated_value_for_display_rv(
        tags$div(
          class = "alert alert-danger",
          style = "font-size: 18px; text-align: center;",
          "Configuração inválida: URL da API não informada."
        )
      )
      return()
    }

    api_response <- tryCatch(
      {
        req <- request(api_url) %>%
          req_body_json(payload) %>%
          req_headers(
            Accept = "application/json",
            `Content-Type` = "application/json"
          ) %>%
          req_timeout(seconds = 20)
        resp <- req_perform(req)
        resp
      },
      error = function(e) {
        showNotification(
          paste("Erro ao conectar à API:", e$message),
          type = "error"
        )
        NULL
      }
    )

    if (is.null(api_response)) {
      prediction_results_rv(data.frame(
        Erro = "Falha na comunicação com a API",
        Detalhes = "Não foi possível obter uma resposta da API."
      ))
      estimated_value_for_display_rv(
        tags$div(
          class = "alert alert-danger",
          style = "font-size: 18px; text-align: center;",
          "Não foi possível estimar o valor: Falha na comunicação com a API."
        )
      )
      return()
    }

    if (!resp_is_error(api_response)) {
      raw_body_string <- tryCatch(
        {
          resp_body_string(api_response)
        },
        error = function(e_str) {
          paste(
            "Não foi possível ler o corpo da resposta como string:",
            e_str$message
          )
        }
      )
      # cat("Corpo da resposta da API (string crua):\n"); print(raw_body_string) # Removido para limpeza, pode ser reativado para debug
    }

    if (resp_is_error(api_response)) {
      status_code <- resp_status(api_response)
      error_details <- tryCatch(
        {
          resp_body_string(api_response)
        },
        error = function(e) {
          paste(
            "Não foi possível ler o corpo da resposta de erro. Status:",
            status_code
          )
        }
      )
      showNotification(
        paste(
          "Erro da API (Status:",
          status_code,
          "):",
          substr(error_details, 1, 200)
        ),
        type = "error"
      )
      prediction_results_rv(data.frame(
        Erro = paste("API retornou erro", status_code),
        Detalhes = substr(error_details, 1, 500)
      ))
      estimated_value_for_display_rv(
        tags$div(
          class = "alert alert-danger",
          style = "font-size: 18px; text-align: center;",
          paste(
            "Não foi possível estimar o valor: Erro da API (Status:",
            status_code,
            ")."
          )
        )
      )
      return()
    }

    prediction_log_value <- tryCatch(
      {
        api_result_list <- resp_body_json(api_response, check_type = FALSE)[[1]]
        # cat("Estrutura da resposta da API após parse JSON:\n"); print(utils::str(api_result_list)) # Removido para limpeza

        extracted_value <- NULL
        if (is.list(api_result_list) && length(api_result_list) > 0) {
          first_item <- api_result_list[[1]]
          if (is.numeric(first_item)) {
            extracted_value <- first_item
          } else if (
            is.list(first_item) &&
              !is.null(first_item$prediction) &&
              is.numeric(first_item$prediction)
          ) {
            extracted_value <- first_item$prediction
          } else if (
            !is.null(api_result_list$prediction) &&
              is.numeric(api_result_list$prediction)
          ) {
            extracted_value <- api_result_list$prediction
          }
        } else if (
          !is.null(api_result_list$prediction) &&
            is.numeric(api_result_list$prediction)
        ) {
          extracted_value <- api_result_list$prediction
        }

        if (is.null(extracted_value)) {
          stop(
            "Formato de resposta da API inesperado."
          )
        }
        extracted_value
      },
      error = function(e) {
        showNotification(
          paste("Erro ao processar resposta da API:", e$message),
          type = "error"
        )
        NULL
      }
    )

    if (is.null(prediction_log_value)) {
      prediction_results_rv(data.frame(
        Erro = "Falha ao processar resposta da API",
        Detalhes = "A API não retornou um valor numérico no formato esperado."
      ))
      estimated_value_for_display_rv(
        tags$div(
          class = "alert alert-danger",
          style = "font-size: 18px; text-align: center;",
          "Não foi possível estimar o valor: Resposta da API inválida."
        )
      )
      return()
    }

    estimated_value <- 10^prediction_log_value

    # --- INÍCIO: Atualizar reactiveVal para display destacado ---
    formatted_estimated_value <- paste0(
      "R$ ",
      format(
        estimated_value,
        big.mark = ".",
        decimal.mark = ",",
        nsmall = 2,
        scientific = FALSE
      )
    )
    estimated_value_for_display_rv(
      tags$div(
        class = "alert alert-success", # Classe Bootstrap para estilo (fundo verde)
        style = "font-size: 28px; text-align: center; font-weight: bold; padding: 20px; margin-bottom: 20px;",
        HTML(paste0(
          "✨ **Valor Estimado do Imóvel** ✨<br>",
          formatted_estimated_value
        ))
      )
    )
    # --- FIM: Atualizar ---

    results_df <- data.frame(
      `Característica` = c(
        "API URL",
        "Endereço Informado",
        "Latitude (Estimada)",
        "Longitude (Estimada)",
        "Tipo de Imóvel",
        "Área (m²)",
        "Quartos",
        "Banheiros",
        "Vagas de Garagem",
        "Área de Serviço",
        "Espaço Gourmet",
        "Piscina",
        "Elevador",
        "Salão de Festa",
        "Academia",
        "Playground",
        "Quadra de Esporte",
        "Portaria 24 Horas",
        "Varanda Gourmet",
        "Sauna",
        "Spa",
        "--- VALOR ESTIMADO (R$) ---" # Esta linha continua na tabela para detalhamento
      ),
      `Valor Informado/Resultado` = c(
        input$api_url,
        input$endereco,
        sprintf("%.5f", latitude_val),
        sprintf("%.5f", longitude_val),
        input$tipo,
        as.character(input$area),
        as.character(input$quarto),
        as.character(input$banheiro),
        as.character(input$vaga),
        ifelse(input$area_servico, "Sim ✅", "Não ❌"),
        ifelse(input$espaco_gourmet, "Sim ✅", "Não ❌"),
        ifelse(input$piscina, "Sim ✅", "Não ❌"),
        ifelse(input$elevador, "Sim ✅", "Não ❌"),
        ifelse(input$salao_de_festa, "Sim ✅", "Não ❌"),
        ifelse(input$academia, "Sim ✅", "Não ❌"),
        ifelse(input$playground, "Sim ✅", "Não ❌"),
        ifelse(input$quadra_de_esporte, "Sim ✅", "Não ❌"),
        ifelse(input$portaria_24_horas, "Sim ✅", "Não ❌"),
        ifelse(input$varanda_gourmet, "Sim ✅", "Não ❌"),
        ifelse(input$sauna, "Sim ✅", "Não ❌"),
        ifelse(input$spa, "Sim ✅", "Não ❌"),
        formatted_estimated_value # Usando o valor já formatado
      ),
      stringsAsFactors = FALSE
    )

    prediction_results_rv(results_df)
    showNotification("Estimativa concluída!", type = "message", duration = 3)
  })

  # --- INÍCIO: RenderUI para o valor estimado destacado ---
  output$highlighted_prediction_output <- renderUI({
    display_content <- estimated_value_for_display_rv()
    if (is.null(display_content)) {
      # Mensagem placeholder antes da primeira estimativa
      return(
        tags$div(
          style = "text-align: center; padding: 15px; font-style: italic; color: #777; border: 1px dashed #ccc; margin-bottom: 20px;",
          "O valor estimado do imóvel será exibido aqui após a consulta."
        )
      )
    }
    return(display_content)
  })
  # --- FIM: RenderUI ---

  output$resultTable <- DT::renderDataTable({
    results <- prediction_results_rv()
    if (is.null(results)) {
      return(DT::datatable(
        data.frame(
          Mensagem = "Os detalhes da estimativa e os parâmetros utilizados aparecerão aqui."
        ),
        options = list(dom = 't', searching = FALSE, paging = FALSE),
        rownames = FALSE,
        colnames = c("")
      ))
    }
    if ("Erro" %in% colnames(results)) {
      DT::datatable(
        results,
        options = list(
          dom = 't',
          pageLength = nrow(results),
          autoWidth = TRUE,
          searching = FALSE,
          paging = FALSE
        ),
        rownames = FALSE,
        caption = htmltools::tags$caption(
          style = "caption-side: top; text-align: center; color: red; font-weight: bold;",
          "Ocorreu um Problema na Estimativa"
        )
      )
    } else {
      DT::datatable(
        results,
        options = list(
          pageLength = nrow(results),
          scrollX = TRUE,
          autoWidth = TRUE,
          searching = FALSE,
          paging = FALSE,
          dom = 't'
        ),
        rownames = FALSE,
        colnames = c("Detalhe", "Valor"),
        caption = htmltools::tags$caption(
          style = "caption-side: top; text-align: center; color: #337ab7; font-weight: bold;",
          "Resumo Detalhado da Estimativa do Imóvel"
        )
      )
    }
  })
}

shinyApp(ui = ui, server = server)
