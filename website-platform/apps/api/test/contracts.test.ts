import assert from 'node:assert/strict';
import { test } from 'node:test';
import { slugSchema, leadSchema, documentSchema } from '../src/contracts';
import { hashPassword, verifyPassword } from '../src/core';
test('rejects unsafe URL slugs',()=>{assert.equal(slugSchema.safeParse('../admin').success,false);assert.equal(slugSchema.safeParse('hello-world').success,true);});
test('requires idempotency keys and disallows unknown lead attributes',()=>{assert.equal(leadSchema.safeParse({name:'A',email:'a@example.com',message:'Please call me'}).success,false);assert.equal(leadSchema.safeParse({name:'A',email:'a@example.com',message:'Please call me',idempotencyKey:'6b419421-3852-4b6c-821a-98b71fcb44aa',privateField:'no'}).success,false);});
test('rejects noncanonical slugs',()=>assert.equal(documentSchema.safeParse({title:'Page',slug:'Spaces Invalid'}).success,false));
test('passwords have unique salts and reject incorrect attempts',()=>{const a=hashPassword('long secure password'),b=hashPassword('long secure password');assert.notEqual(a,b);assert.equal(verifyPassword('long secure password',a),true);assert.equal(verifyPassword('incorrect',a),false);});
