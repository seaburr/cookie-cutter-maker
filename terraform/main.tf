resource "digitalocean_app" "cookie_cutter_maker" {
  spec {
    name   = "cookie-cutter-maker"
    region = var.region

    domain {
      name = "cookies.seaburr.io"
      type = "PRIMARY"
      zone = "seaburr.io"
    }

    service {
      name               = "api"
      instance_count     = var.instance_count
      instance_size_slug = var.instance_size_slug
      http_port          = 8000

      image {
        registry_type        = "GHCR"
        registry             = "seaburr"
        repository           = "cookie-cutter-maker"
        tag                  = var.image_tag
        deploy_on_push {
          enabled = true
        }
      }

      health_check {
        http_path             = "/healthz"
        initial_delay_seconds = 30
        period_seconds        = 30
        timeout_seconds       = 5
      }

      env {
        key   = "PIPELINE_OUTPUT_DIR"
        value = "/app/output"
        scope = "RUN_TIME"
      }

      env {
        key   = "REMBG_ENABLED"
        value = var.rembg_enabled
        scope = "RUN_TIME"
      }

      dynamic "env" {
        for_each = var.access_password != "" ? [var.access_password] : []
        content {
          key   = "ACCESS_PASSWORD"
          value = env.value
          scope = "RUN_TIME"
          type  = "SECRET"
        }
      }

      dynamic "env" {
        for_each = var.openai_api_key != "" ? [var.openai_api_key] : []
        content {
          key   = "OPENAI_API_KEY"
          value = env.value
          scope = "RUN_TIME"
          type  = "SECRET"
        }
      }

      dynamic "env" {
        for_each = var.session_secret != "" ? [var.session_secret] : []
        content {
          key   = "SESSION_SECRET"
          value = env.value
          scope = "RUN_TIME"
          type  = "SECRET"
        }
      }
    }
  }
}
