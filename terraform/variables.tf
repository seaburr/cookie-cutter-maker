variable "do_token" {
  description = "DigitalOcean personal access token."
  type        = string
  sensitive   = true
}

variable "image_tag" {
  description = "Docker image tag to deploy."
  type        = string
  default     = "latest"
}

variable "region" {
  description = "DigitalOcean App Platform region slug (e.g. nyc, ams, sfo, fra, lon, sgp, syd, tor)."
  type        = string
  default     = "nyc"
}

variable "instance_size_slug" {
  description = "App Platform instance size slug."
  type        = string
  default     = "apps-s-1vcpu-1gb-fixed"
}

variable "instance_count" {
  description = "Number of instances to run."
  type        = number
  default     = 1
}

variable "rembg_enabled" {
  description = "Set to 'false' to disable rembg background removal (falls back to graph-cut segmentation)."
  type        = string
  default     = "false"
}

variable "openai_api_key" {
  description = "Optional OpenAI API key to enable prompt-to-outline generation."
  type        = string
  sensitive   = true
  default     = ""
}
