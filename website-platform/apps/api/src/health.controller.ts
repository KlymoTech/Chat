import {Controller,Get,ServiceUnavailableException} from '@nestjs/common';
import {Db} from './core';
@Controller('v1/health')
export class HealthController {
 constructor(private readonly db:Db){}
 @Get('live') live(){return {status:'alive'};}
 @Get('ready') async ready(){
  try{await this.db.$queryRawUnsafe('SELECT 1');return {status:'ready'};}
  catch{throw new ServiceUnavailableException('Database unavailable');}
 }
}
