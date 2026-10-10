import {describe,expect,it} from "vitest";
import {parseBlogClassification} from "../src/lib/blog-contract";

describe("blog editorial taxonomy contract",()=>{
  it("normalizes approved category and tag slugs",()=>{
    expect(parseBlogClassification({
      category:"  Product-Updates  ",tags:["  Releases ","Implementation-Guides"]
    })).toEqual({category:"product-updates",tags:["releases","implementation-guides"]});
  });
  it("permits an untagged article but always requires a category",()=>{
    expect(parseBlogClassification({category:"guidance",tags:[]})).toEqual({
      category:"guidance",tags:[]
    });
    expect(parseBlogClassification({category:"",tags:[]})).toBeNull();
  });
  it("rejects duplicate tags, HTML, URLs and unsafe characters",()=>{
    for(const value of [
      {category:"guidance",tags:["demo","DEMO"]},
      {category:"guide<script>",tags:[]},
      {category:"guidance",tags:["https://example.com"]},
      {category:"guidance",tags:["free trial"]},
      {category:"guidance",tags:["x".repeat(41)]},
      {category:"x".repeat(61),tags:[]},
      {category:"guidance",tags:Array.from({length:9},(_,i)=>"tag-"+i)},
      {category:"guidance",tags:"marketing"},
      null
    ])expect(parseBlogClassification(value)).toBeNull();
  });
});
