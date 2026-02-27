terraform {
  required_version = ">= 1.3"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.78"
    }
  }
}

provider "digitalocean" {
  token = var.do_token
}
