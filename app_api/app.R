library(shiny)
library(jsonlite)
library(httr)
library(shinycssloaders) # Para o spinner de carregamento

# Define a interface do usuário (UI)
ui <- fluidPage(
  # Adiciona um tema básico para melhorar a aparência
  theme = bslib::bs_theme(version = 4, bootswatch = "flatly"),

  titlePanel(
    div(
      class = "text-center text-primary font-weight-bold my-4",
      icon("chart-line"),
      "Aplicação que consome uma API do modelo lasso com 20 variáveis preditoras"
    )
  ),

  sidebarLayout(
    sidebarPanel(
      class = "bg-light p-4 rounded shadow-sm",
      h3(class = "text-info mb-3", icon("cogs"), "Configurações da API"),
      textInput(
        inputId = "apiUrl",
        label = "URL da API de Previsão:",
        value = "http://localhost:8080/predict",
        placeholder = "Ex: http://localhost:8080/predict"
      ),
      actionButton(
        inputId = "generatePredict",
        label = "Gerar Inputs e Prever",
        icon = icon("magic"),
        class = "btn-primary btn-lg w-100 mt-3"
      ),
      hr(),
      p(
        class = "text-muted text-sm",
        "Clique no botão para gerar 20 valores aleatórios e enviá-los para a API especificada para obter uma previsão."
      )
    ),

    mainPanel(
      class = "p-4",
      fluidRow(
        column(
          12,
          div(
            class = "card shadow-sm mb-4",
            div(
              class = "card-header bg-info text-white",
              h4(
                class = "card-title mb-0",
                icon("list-ol"),
                "Inputs Gerados (X1 a X20):"
              )
            ),
            div(class = "card-body", verbatimTextOutput("generatedInputs"))
          )
        )
      ),
      fluidRow(
        column(
          12,
          div(
            class = "card shadow-sm",
            div(
              class = "card-header bg-success text-white",
              h4(
                class = "card-title mb-0",
                icon("chart-bar"),
                "Resultado da Previsão:"
              )
            ),
            div(
              class = "card-body",
              # Adiciona um spinner de carregamento antes do resultado
              withSpinner(
                verbatimTextOutput("predictionResult"),
                type = 6,
                color = "#28a745"
              )
            )
          )
        )
      )
    )
  )
)

# Define a lógica do servidor
server <- function(input, output, session) {
  app_data <- reactiveValues(
    inputs = NULL,
    prediction = "Nenhuma previsão ainda."
  )

  observeEvent(input$generatePredict, {
    # Limpa mensagens de erro e resultados anteriores
    app_data$prediction <- "Processando..."
    app_data$inputs <- NULL

    # Geração dos 20 inputs (X1 a X20)
    generated_x <- rnorm(20, mean = 0, sd = 1)
    names(generated_x) <- paste0("x", 1:20) # Note que agora usamos 'x' minúsculo

    # Armazena os inputs gerados
    app_data$inputs <- generated_x

    # Prepara os dados no formato exato que a API espera
    # Criamos uma lista de um único elemento que contém todos os x's
    api_payload <- list(as.list(generated_x))

    # Converte para JSON mantendo a estrutura idêntica ao exemplo do curl
    json_payload <- toJSON(api_payload, auto_unbox = TRUE)

    # Faz a chamada POST para a API
    response <- tryCatch(
      {
        POST(
          url = input$apiUrl,
          add_headers(
            "accept" = "application/json",
            "content-type" = "application/json"
          ),
          body = json_payload,
          encode = "raw",
          timeout = 10 # Adiciona um timeout para evitar esperas infinitas
        )
      },
      error = function(e) {
        message("Erro ao conectar à API: ", e$message)
        return(NULL)
      }
    )

    # Processa a resposta
    if (!is.null(response) && status_code(response) == 200) {
      tryCatch(
        {
          api_content <- content(response, "text", encoding = "UTF-8")
          parsed_response <- fromJSON(api_content)

          # Tenta extrair a previsão de forma mais limpa se for o formato esperado
          if (
            is.list(parsed_response) &&
              length(parsed_response) > 0 &&
              is.list(parsed_response[[1]]) &&
              !is.null(parsed_response[[1]][[".pred"]])
          ) {
            prediction_value <- parsed_response[[1]][[".pred"]]
            app_data$prediction <- paste(
              "Previsão:",
              round(prediction_value, 4)
            ) # Arredonda para 4 casas decimais
          } else {
            # Caso contrário, mostra o JSON formatado
            app_data$prediction <- toJSON(
              parsed_response,
              pretty = TRUE,
              auto_unbox = TRUE
            )
          }
        },
        error = function(e) {
          app_data$prediction <- paste(
            "Erro ao processar resposta da API:",
            e$message,
            "\nResposta bruta:",
            content(response, "text", encoding = "UTF-8")
          )
        }
      )
    } else if (!is.null(response)) {
      app_data$prediction <- paste(
        "Erro na API:",
        status_code(response),
        "-",
        http_status(response)$message,
        "\nResposta:",
        content(response, "text", encoding = "UTF-8")
      )
    } else {
      app_data$prediction <- "Não foi possível conectar à API. Verifique o URL e se a API está ativa. (Erro de rede ou timeout)"
    }
  })

  output$generatedInputs <- renderPrint({
    if (!is.null(app_data$inputs)) {
      app_data$inputs
    } else {
      "Clique em 'Gerar Inputs e Prever' para ver os inputs."
    }
  })

  output$predictionResult <- renderPrint({
    app_data$prediction
  })
}

# Executa o aplicativo
shinyApp(ui = ui, server = server)
