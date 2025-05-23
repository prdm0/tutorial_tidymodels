# app.R

library(shiny)
library(jsonlite)
library(httr)

# Define a interface do usuário (UI)
ui <- fluidPage(
  titlePanel("Gerador de Inputs e Previsor de API"),

  sidebarLayout(
    sidebarPanel(
      textInput(
        inputId = "apiUrl",
        label = "URL da API de Previsão:",
        value = "http://localhost:8080/predict",
        placeholder = "Ex: http://localhost:8080/predict"
      ),
      actionButton(
        inputId = "generatePredict",
        label = "Gerar Inputs e Prever"
      )
    ),

    mainPanel(
      h4("Inputs Gerados (X1 a X20):"),
      verbatimTextOutput("generatedInputs"),

      h4("Resultado da Previsão:"),
      verbatimTextOutput("predictionResult")
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
          encode = "raw"
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
          app_data$prediction <- parsed_response
        },
        error = function(e) {
          app_data$prediction <- paste("Erro ao processar resposta:", e$message)
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
      app_data$prediction <- "Não foi possível conectar à API. Verifique o URL e se a API está ativa."
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
