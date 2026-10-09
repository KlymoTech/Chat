import {
  BadRequestException, Body, Controller, Get, Param, Patch, Post, Req, UseGuards,
} from '@nestjs/common';
import { z } from 'zod';
import { Db, AdminGuard, AdminRequest, parseInput, requireRevision } from './core';
import { documentSchema, siteSchema } from './contracts';
const leadState = z.object({ status: z.enum(['NEW','CONTACTED','QUALIFIED','CLOSED']) }).strict();

@Controller('v1/admin')
@UseGuards(AdminGuard)
export class AdminController {
  constructor(private readonly db: Db) {}
  private site() { return this.db.site.findUniqueOrThrow({where:{key:'default'}}); }
  @Get('summary') async summary() {
    const site = await this.site();
    const [pages, articles, leads, pendingJobs] = await Promise.all([
      this.db.page.count({where:{siteId:site.id}}),
      this.db.article.count({where:{siteId:site.id}}),
      this.db.lead.count({where:{siteId:site.id}}),
      this.db.outboxEvent.count({where:{state:'PENDING'}})
    ]);
    return {pages,articles,leads,pendingJobs};
  }
  @Get('site') getSite() {return this.site();}
  @Patch('site') async updateSite(@Body() raw:unknown,@Req() req:AdminRequest) {
    const input=parseInput(siteSchema,raw), site=await this.site();
    return this.db.$transaction(async tx=>{
      const next=await tx.site.update({where:{id:site.id},data:input});
      await tx.auditEvent.create({data:{actorId:req.adminId,action:'site.update',entity:'site',entityId:site.id,details:input}});
      await tx.outboxEvent.create({data:{topic:'site.changed',payload:{siteId:site.id}}});
      return next;
    });
  }
  @Get('pages') async pages() {
    const site=await this.site();
    return this.db.page.findMany({where:{siteId:site.id},orderBy:{updatedAt:'desc'},take:200});
  }
  @Post('pages') async createPage(@Body() raw:unknown,@Req() req:AdminRequest) {
    const data=parseInput(documentSchema,raw),site=await this.site();
    return this.db.$transaction(async tx=>{
      const page=await tx.page.create({data:{siteId:site.id,slug:data.slug,title:data.title,body:data.body,description:data.description}});
      await tx.auditEvent.create({data:{actorId:req.adminId,action:'page.create',entity:'page',entityId:page.id,details:{slug:page.slug}}});
      return page;
    });
  }
  @Patch('pages/:id') async savePage(@Param('id') id:string,@Body() raw:unknown,@Req() req:AdminRequest) {
    const data=parseInput(documentSchema,raw),site=await this.site();
    return this.db.$transaction(async tx=>{
      const prior=await tx.page.findFirstOrThrow({where:{id,siteId:site.id}});
      requireRevision(data.revision,prior.draftVersion);
      if(prior.status==='PUBLISHED' && prior.slug!==data.slug) throw new BadRequestException('Use a managed redirect before changing a published URL');
      const updated=await tx.page.update({where:{id},data:{title:data.title,slug:data.slug,body:data.body,description:data.description,draftVersion:{increment:1}}});
      await tx.auditEvent.create({data:{actorId:req.adminId,action:'page.draft.save',entity:'page',entityId:id,details:{draftVersion:updated.draftVersion}}});
      return updated;
    });
  }
  @Post('pages/:id/publish') async publishPage(@Param('id') id:string,@Req() req:AdminRequest) {
    const site=await this.site();
    return this.db.$transaction(async tx=>{
      const page=await tx.page.findFirstOrThrow({where:{id,siteId:site.id}});
      const revision=page.revision+1,snapshot={slug:page.slug,title:page.title,description:page.description,body:page.body};
      const updated=await tx.page.update({where:{id},data:{status:'PUBLISHED',publishedSnapshot:snapshot,revision,publishedAt:new Date(),draftVersion:{increment:1}}});
      await tx.pageRevision.create({data:{pageId:id,revision,snapshot,actorId:req.adminId}});
      await tx.auditEvent.create({data:{actorId:req.adminId,action:'page.publish',entity:'page',entityId:id,details:{revision}}});
      await tx.outboxEvent.create({data:{topic:'page.published',payload:{siteId:site.id,id,slug:page.slug,revision}}});
      return updated;
    });
  }
  @Get('pages/:id/revisions') async pageHistory(@Param('id') id:string) {
    const site=await this.site();
    await this.db.page.findFirstOrThrow({where:{id,siteId:site.id}});
    return this.db.pageRevision.findMany({where:{pageId:id},orderBy:{revision:'desc'},take:100});
  }
  @Get('articles') async articles() {
    const site=await this.site();
    return this.db.article.findMany({where:{siteId:site.id},orderBy:{updatedAt:'desc'},take:200});
  }
  @Post('articles') async createArticle(@Body() raw:unknown,@Req() req:AdminRequest) {
    const data=parseInput(documentSchema,raw),site=await this.site();
    return this.db.$transaction(async tx=>{
      const article=await tx.article.create({data:{siteId:site.id,slug:data.slug,title:data.title,body:data.body,description:data.description}});
      await tx.auditEvent.create({data:{actorId:req.adminId,action:'article.create',entity:'article',entityId:article.id,details:{slug:article.slug}}});
      return article;
    });
  }
  @Patch('articles/:id') async saveArticle(@Param('id') id:string,@Body() raw:unknown,@Req() req:AdminRequest) {
    const data=parseInput(documentSchema,raw),site=await this.site();
    return this.db.$transaction(async tx=>{
      const prior=await tx.article.findFirstOrThrow({where:{id,siteId:site.id}});
      requireRevision(data.revision,prior.draftVersion);
      if(prior.status==='PUBLISHED' && prior.slug!==data.slug) throw new BadRequestException('Use a managed redirect before changing a published URL');
      const updated=await tx.article.update({where:{id},data:{title:data.title,slug:data.slug,body:data.body,description:data.description,draftVersion:{increment:1}}});
      await tx.auditEvent.create({data:{actorId:req.adminId,action:'article.draft.save',entity:'article',entityId:id,details:{draftVersion:updated.draftVersion}}});
      return updated;
    });
  }
  @Post('articles/:id/publish') async publishArticle(@Param('id') id:string,@Req() req:AdminRequest) {
    const site=await this.site();
    return this.db.$transaction(async tx=>{
      const article=await tx.article.findFirstOrThrow({where:{id,siteId:site.id}});
      const revision=article.revision+1,snapshot={slug:article.slug,title:article.title,description:article.description,body:article.body};
      const updated=await tx.article.update({where:{id},data:{status:'PUBLISHED',publishedSnapshot:snapshot,revision,publishedAt:new Date(),draftVersion:{increment:1}}});
      await tx.articleRevision.create({data:{articleId:id,revision,snapshot,actorId:req.adminId}});
      await tx.auditEvent.create({data:{actorId:req.adminId,action:'article.publish',entity:'article',entityId:id,details:{revision}}});
      await tx.outboxEvent.create({data:{topic:'article.published',payload:{siteId:site.id,id,slug:article.slug,revision}}});
      return updated;
    });
  }
  @Get('articles/:id/revisions') async articleHistory(@Param('id') id:string) {
    const site=await this.site();
    await this.db.article.findFirstOrThrow({where:{id,siteId:site.id}});
    return this.db.articleRevision.findMany({where:{articleId:id},orderBy:{revision:'desc'},take:100});
  }
  @Get('leads') async leads() {
    const site=await this.site();
    return this.db.lead.findMany({where:{siteId:site.id},orderBy:{createdAt:'desc'},take:100});
  }
  @Patch('leads/:id') async updateLead(@Param('id') id:string,@Body() raw:unknown,@Req() req:AdminRequest) {
    const input=parseInput(leadState,raw),site=await this.site();
    return this.db.$transaction(async tx=>{
      await tx.lead.findFirstOrThrow({where:{id,siteId:site.id}});
      const updated=await tx.lead.update({where:{id},data:input});
      await tx.auditEvent.create({data:{actorId:req.adminId,action:'lead.status',entity:'lead',entityId:id,details:input}});
      return updated;
    });
  }
  @Get('audit') audit() {return this.db.auditEvent.findMany({orderBy:{createdAt:'desc'},take:100});}
  @Get('outbox') outbox() {return this.db.outboxEvent.findMany({select:{id:true,topic:true,state:true,attempts:true,createdAt:true},orderBy:{createdAt:'desc'},take:100});}
}
