import { Module } from '@nestjs/common';
import { Db, AdminGuard } from './core';
import { PublicController } from './public.controller';
import { AdminController } from './admin.controller';
import { AuthController } from './auth.controller';

@Module({
  controllers: [PublicController, AdminController, AuthController],
  providers: [Db, AdminGuard],
})
export class AppModule {}
