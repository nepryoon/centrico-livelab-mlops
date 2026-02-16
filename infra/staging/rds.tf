resource "aws_db_subnet_group" "default" {
  name       = "${var.app_prefix}-db-subnets"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_security_group" "rds" {
  name        = "${var.app_prefix}-rds-sg"
  description = "Allow Postgres from ECS tasks"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "postgres" {
  identifier = "${var.app_prefix}-stg-postgres"

  engine         = "postgres"
  engine_version = "16"

  instance_class    = "db.t4g.micro"
  allocated_storage = 20

  db_name  = "livelab"
  username = "app"
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.default.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  publicly_accessible      = false
  skip_final_snapshot      = true
  deletion_protection      = false
  delete_automated_backups = true
}
