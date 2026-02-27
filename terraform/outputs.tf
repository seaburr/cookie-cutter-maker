output "app_url" {
  description = "Live URL of the deployed application."
  value       = digitalocean_app.cookie_cutter_maker.live_url
}

output "app_id" {
  description = "DigitalOcean App Platform app ID."
  value       = digitalocean_app.cookie_cutter_maker.id
}
