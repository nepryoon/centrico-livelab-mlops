# Application Load Balancer - Internet-facing load balancer for inference service
resource "aws_lb" "app" {
  name               = "${var.app_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [aws_subnet.public_1.id, aws_subnet.public_2.id]

  enable_deletion_protection = false
  enable_http2               = true

  tags = {
    Name = "${var.app_prefix}-alb"
  }
}

# Target Group - Routes traffic to ECS tasks on port 8000
resource "aws_lb_target_group" "inference" {
  name        = "${var.app_prefix}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30

  tags = {
    Name    = "${var.app_prefix}-tg"
    Service = "inference"
  }
}

# ALB Listener - HTTP:80 forwards to target group
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.inference.arn
  }

  tags = {
    Name = "${var.app_prefix}-listener-http"
  }
}
