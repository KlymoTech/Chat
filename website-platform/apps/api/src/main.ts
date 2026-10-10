import 'dotenv/config';
import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';

async function bootstrap() {
  if (!process.env.DATABASE_URL || !process.env.WEB_ORIGIN) {
    throw new Error('DATABASE_URL and WEB_ORIGIN are required');
  }
  const app = await NestFactory.create(AppModule, { bodyParser: true });
  app.enableShutdownHooks();
  app.enableCors({ origin: process.env.WEB_ORIGIN, credentials: true });
  await app.listen(Number(process.env.API_PORT ?? 4100), '0.0.0.0');
}
void bootstrap();
