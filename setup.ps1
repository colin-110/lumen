Write-Host "Setting up Lumen..." -ForegroundColor Green

# 1. Copy Backend ENV
if (-not (Test-Path "backend\.env")) {
    Copy-Item -Path ".env.example" -Destination "backend\.env"
    Write-Host "Created backend\.env. Please update it with your API keys!" -ForegroundColor Yellow
} else {
    Write-Host "backend\.env already exists. Skipping."
}

# 2. Copy Frontend ENV
if (-not (Test-Path "frontend\.env.local")) {
    Set-Content -Path "frontend\.env.local" -Value "NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1"
    Write-Host "Created frontend\.env.local" -ForegroundColor Yellow
} else {
    Write-Host "frontend\.env.local already exists. Skipping."
}

Write-Host "Setup complete! You can now run docker-compose up -d" -ForegroundColor Green
